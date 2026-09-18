# ADR-070: Credential rotation without a restart

## Status

Proposed

## Context

Credential rotation does not work today. `@syntropic137/setup credentials rotate`
is parsed, tested and referenced in help text, but the handler prints a warning
and exits. It was disabled deliberately (npx#56), and the stated reason was:

> Rotation updates `.env` and secret files but the event store password is baked
> in at container init time, so after a stack restart the event store can no
> longer authenticate to the database, breaking the system with no safe recovery
> path.

Disabling it was the right call. A rotation that bricks the event store is worse
than no rotation. But the reasoning contains one claim that is wrong, and that
error is why the feature stayed off rather than getting fixed.

### What was measured

Four things were established by experiment on 2026-09-06 and 2026-09-07 rather
than by reading documentation.

**1. `POSTGRES_PASSWORD` is honoured only at initdb.** A scratch
`timescale/timescaledb:2.29.2-pg16` was initialised with one password, then
recreated on the same volume with a different one. Over TCP with
`scram-sha-256`, the new password was rejected and the original accepted. The
env var is ignored once `PGDATA` exists, and the real password lives in the
database.

This is the lockout mechanism precisely: rotation writes a new secret file, the
stack restarts, and all three clients present a password the server never
adopted.

A first attempt at this experiment appeared to show both passwords working. That
run was invalid: `docker exec psql` connects over the local socket, and the
image ships `local all all trust`, so no password was ever checked. The result
is recorded here because the invalid version is the more tempting experiment to
run.

**2. A safe recovery path does exist.** `ALTER ROLE syn PASSWORD '<new>'`
executed through `docker exec` succeeds **without the old password**, precisely
because of that `local ... trust` line. Afterwards the new password is accepted
over TCP and the old one rejected.

So the claim of "no safe recovery path" is false, and rollback is symmetric and
always available: the same command with the previous value.

**3. Both drivers resolve credentials per connection.** `asyncpg` accepts a
callable password and invokes it once per connection, not once per pool
(five backends produced five invocations, counted against the server's own
`pg_stat_activity` and backend PIDs). `redis.asyncio` does the same through a
`CredentialProvider` object, invoked inside `on_connect`, so once per socket.
Both hold at the declared floors (`asyncpg==0.30.0`, `redis==5.0.0`), not only
at locked versions. A password was rotated mid-process and new connections
authenticated with no restart, while static-password controls broke at the same
moment.

Full method and limitations: `docs/experiments/2026-09-06-driver-credential-rotation.md`.

**4. The blast radius is small.** `DATABASE_URL` has one non-test reference and
`REDIS_URL` has five. The file-backed pattern already exists and is already
documented as preferred: `SYN_GITHUB_APP_PRIVATE_KEY_FILE`, whose settings code
says "prefer this for Docker deployments". The architecture reached this
conclusion once and never extended it to the other three credentials.

### Why the current shape makes rotation hard

`selfhost-entrypoint.sh` reads Docker secrets and expands them into environment
variables at container start:

```sh
export DATABASE_URL="postgres://syn:${POSTGRES_PASSWORD}@timescaledb:5432/syn"
export REDIS_URL="redis://:${REDIS_PASSWORD}@redis:6379/0"
```

Two consequences follow, and both are load-bearing.

The credential is **fixed for the life of the process**, so any change requires a
restart. Restarting the API orphans every running execution (#1179), which makes
rotation something an operator avoids rather than something routine.

And the credential is **readable by everything the process can reach**. It sits
in `/proc/<pid>/environ` and in any dump of `os.environ`. This is not
theoretical: while researching this ADR, a masked probe of that exact surface
leaked a live database password into a session transcript because a shell
quoting bug silently broke the masker. No error was raised and the output looked
redacted.

That incident is the strongest argument in this document. Redaction is not a
control, because it depends on the redactor being correct in every tool, on
every path, under every quoting edge case. The durable answer is for the value
not to be there.

### Service and credential map

| Credential | Server | Clients |
|---|---|---|
| `db_password` | timescaledb | api, event-store, collector |
| `redis_password` | redis | api |
| `minio_password` | minio | api |
| `github_app_private_key` | GitHub | api |

`db_password` is the difficult one and the one npx#56 names: one server, three
clients, all reading it at init.

## Decision

### D1. Credentials are resolved at connect time from a file, never expanded into the environment

The application obtains each credential through a provider that reads a file
when a connection is opened. `DATABASE_URL` and `REDIS_URL` carry no password.
This extends the existing `SYN_GITHUB_APP_PRIVATE_KEY_FILE` pattern to the
remaining three credentials rather than inventing a new one.

The property being bought is not convenience. It is that a credential absent
from the environment cannot be leaked by an environment dump, a traceback, a
`/proc` read, or a redaction bug.

### D2. Rotation changes the server's credential first, through a path that does not require the old one

For Postgres this is `ALTER ROLE` over the local trust socket. Ordering matters:
the server must accept the new credential before any client presents it.

### D3. Rotation is verified against each service, never against the file

Writing a file is not evidence that a credential works. Each rotation ends by
opening a real connection per affected service and confirming the server
accepted the new value. A rotation that cannot verify reports failure and rolls
back.

This is the specific gap in the disabled implementation: it changed files and
reported success, and the mismatch only surfaced at the next restart.

### D4. Rotation does not require a restart

Given D1, a rotated credential is adopted by new connections while existing
pooled connections continue on the credential they authenticated with. The
cutover is a rolling drain rather than an event, and no execution is orphaned.

### D5. Rotation is drain-aware

Even without a restart, rotation is a control-plane operation. It consults the
same in-flight check used before deployment (#1179 / #1181) and refuses to
proceed silently while work is running. Unknown is never reported as clear.

### D6. Rollback is symmetric and always available

Every rotation writes the previous value to a backup before changing anything,
and rollback is the same mechanism as rotation with the previous value. Because
D2 never requires the old credential, rollback cannot be locked out by the
failure it is recovering from.

## Consequences

### Positive

Rotation stops being a feature that is too dangerous to enable. Credentials
leave the process environment, which removes an entire class of leak rather than
mitigating it. The verification requirement in D3 means a rotation that half
worked reports failure instead of waiting to surface at the next restart.

### Negative

Every new connection performs a file read. Under the connection churn currently
observed on the reference deployment (42,439 connections received against 2
concurrently connected, see #1230) that is a per-connect syscall, and it is
unmeasured. It is very likely negligible; it is not yet known to be.

The change touches the entrypoint, the settings layer and the published compose,
all of which reach every selfhost deployment. Existing installations continue to
work only if the env-var path is kept as a fallback during migration.

### Neutral

This ADR does not cover the GitHub App private key, which is already
file-backed, nor `SYN_API_PASSWORD`, which is a gateway credential rather than a
service-to-service one and follows a different lifecycle.

Nothing here changes where secrets come from. ADR-045 remains authoritative for
sourcing, prefixes and vault layout; this ADR governs how a credential changes
while the system is running.

## Open questions

The following are deliberately unresolved and should not be guessed at:

- Whether the repo's `settings.redis_url` and `db_url` plumbing can cleanly
  surrender its embedded password is a design question the driver experiment
  explicitly did not answer.
- Redis and MinIO both support genuinely additive credentials (ACL users,
  service accounts) where Postgres, with a single role, does not. Whether to use
  that asymmetry or hold all four to the same simpler sequence is undecided.
- The per-connect file read cost under real churn is unmeasured.

## References

- ADR-045: Secrets Management Standard (sourcing; this ADR governs rotation)
- ADR-024: Setup Phase Secrets
- `docs/experiments/2026-09-06-driver-credential-rotation.md`
- syntropic137-npx#56: credential rotation disabled
- #1179 / #1181: refuse to act while executions are in flight
- #1230: Redis CPU cap and the connection churn measurement
