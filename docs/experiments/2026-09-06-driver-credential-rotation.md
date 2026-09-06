# Can asyncpg and redis-py pick up a rotated credential without a restart?

Date: 2026-09-06. Experiment only — **no production code was changed.**

Question: can the two drivers this repo actually uses obtain a credential *at
connect time* from a file, so that rotating that file is picked up by NEW
connections without restarting the process?

Drivers under test, and where they are used here:

| Driver | Declared floor | Resolved in `uv.lock` | Real call site |
|---|---|---|---|
| `asyncpg` | `>=0.30.0` (`apps/syn-api/pyproject.toml:15`) | 0.31.0 | `apps/syn-api/src/syn_api/_wiring_db.py:41` — `asyncpg.create_pool(str(db_url), ...)` |
| `redis` | `>=5.0.0` (`packages/syn-adapters/pyproject.toml:18`) | 7.4.0 | `packages/syn-adapters/src/syn_adapters/redis_client.py:27` — `Redis.from_url(url, ...)`, called from `apps/syn-api/src/syn_api/_wiring.py:623` and `:808` |

> Call-site correction: the task names `aioredis.from_url(...)` at
> `_wiring.py:624` / `:810`. There is no `aioredis` dependency; the name is a
> local import alias (`import redis.asyncio as aioredis`,
> `packages/syn-adapters/tests/dedup/test_redis_dedup_integration.py:21`). The
> `.from_url` call is one hop away in `resilient_redis_client`, and lines 623 /
> 808 are the calls to it. The driver family the task means — redis-py asyncio —
> is correct.

## Answers

| | Answer |
|---|---|
| **Q1** | **Yes.** `asyncpg.create_pool(password=...)` accepts a callable (sync or awaitable); `connect_utils.py:1034-1038` resolves it. |
| **Q2** | **Once per connection**, not once per pool. 5 backends → 5 invocations, counted against the server's own `pg_stat_activity` and backend PIDs. |
| **Q3** | **Yes, and also once per connection** — but only via a `CredentialProvider` object, not a bare callable. `redis.asyncio` calls `get_credentials_async()` inside `on_connect`, i.e. per socket. 5 sockets → 5 invocations. A *reused* pooled connection does not re-invoke it (no new socket, no re-auth). |
| **Q4** | **Yes for both.** Password rotated mid-process; new connections authenticated with the new password against a real server, no restart. Static-password controls broke at the same moment, so the success is not a false positive. |

Both mechanisms are present at the **declared floors** (`asyncpg==0.30.0`,
`redis==5.0.0`), not just at the locked versions — verified against the same
servers (see [Floor versions](#floor-versions)).

## How this was run: real servers, no Docker

The repo's normal path (`just test-stack`, then testcontainers) is unavailable
in this workspace. Proof:

```
$ command -v docker
exit=1                       # docker is not installed at all

$ just test-stack            # justfile:821-824 -> `docker compose ... up -d --build`
                             # cannot run: no docker binary

$ .venv/bin/python -c "from testcontainers.postgres import PostgresContainer
  PostgresContainer('timescale/timescaledb:2.29.2-pg16').start()"
docker.errors.DockerException: Error while fetching server API version:
  ('Connection aborted.', FileNotFoundError(2, 'No such file or directory'))
```

Ports 5432 / 15432 / 6379 / 16379 all refused, and no `*DATABASE_URL*` /
`*REDIS_URL*` env vars are set. So the fixtures' three-way auto-detect
(env vars > test-stack > testcontainers) has nothing to find.

**However, a source-only answer was not necessary.** PyPI is reachable and both
servers ship as ordinary Python wheels, so real servers were obtained without
Docker and without root:

```bash
uv venv ~/srvvenv && uv pip install --python ~/srvvenv/bin/python pgserver redislite
# PostgreSQL 16.2  (pgserver 0.1.4)   -> 127.0.0.1:15499, scram-sha-256, role `rotuser`
# Redis 6.2.14     (redislite 6.2.x)  -> 127.0.0.1:16399, requirepass
```

(One wrinkle worth recording: `/tmp` is mounted `noexec`, so the venv must live
outside it — `ImportError: failed to map segment from shared object` otherwise.)

Both servers enforce real authentication before any experiment ran:

```
$ PGPASSWORD=pw-v1 psql -h 127.0.0.1 -p 15499 -U rotuser -d rotdb -c "select 'auth ok as '||current_user"
 auth ok as rotuser
$ PGPASSWORD=wrong psql ...
psql: error: ... FATAL:  password authentication failed for user "rotuser"

$ redis-cli -p 16399 -a rpw-v1 ping
PONG
$ redis-cli -p 16399 -a wrong ping
AUTH failed: WRONGPASS invalid username-password pair or user is disabled.
```

**Everything below asserts on server-side facts** — backend PIDs from
`pg_stat_activity`, `CLIENT ID`/`CLIENT LIST` from redis, the PostgreSQL
connection log, and the server's own rejections — not on what the client
believed it sent. With scram-sha-256 in particular, a successful login is
itself server-side proof that the client knew the password currently stored in
`pg_authid`; the client cannot fake it.

Scripts are in [`driver-credential-rotation/`](driver-credential-rotation/) and
are re-runnable against any Postgres/Redis.

## Q1 + Q2 — asyncpg

**Mechanism**, `asyncpg/connect_utils.py:1033-1039` (installed 0.31.0), inside
`_connect_addr`, which runs once per connection attempt:

```python
params_input = params
if callable(params.password):
    password = params.password()
    if inspect.isawaitable(password):
        password = await password
    params = params._replace(password=password)
```

The pool never resolves it early: `Pool._get_new_connection`
(`asyncpg/pool.py:537-544`) re-calls `self._connect(*self._connect_args,
**self._connect_kwargs)` for every new connection, so the un-resolved callable
is handed to the full connect path each time.

**Empirical run** (`exp_asyncpg.py`, callable reads `~/exp/pgpassword` on every
call):

```
$ .venv/bin/python docs/experiments/driver-credential-rotation/exp_asyncpg.py \
    127.0.0.1 15499 "postgresql://postgres@/postgres?host=/home/agent/exp/pgdata&port=15499"
Q1 create_pool(password=callable)          ACCEPTED (pool created)
server-side distinct backend PIDs          5 [1187, 1188, 1189, 1190, 1191]
server-side pg_stat_activity count         5
callable invocations                       5
Q2 verdict                                 ONCE PER CONNECTION (5 backends -> 5 calls)
server verifier after rotation             SCRAM-SHA-256$4096:WNI0NR9Byj7
old password, fresh connection             REJECTED: password authentication failed for user "rotuser"
post-rotation backend PIDs                 5 [1193, 1194, 1195, 1196, 1197]
overlap with pre-rotation PIDs             []
post-rotation callable invocations         5 -> ['pw-v2']
server says current_user is                rotuser
Q4 asyncpg verdict                         YES - rotation picked up, no restart
static-password pool after rotation        BROKEN: password authentication failed for user "rotuser"
callable pool after 2nd rotation           alive
```

The server's own log for that run, with `log_connections = on`:

```
19:47:21.631 [1187] rotuser@rotdb LOG:  connection authenticated: identity="rotuser" method=scram-sha-256 (pg_hba.conf:119)
19:47:21.669 [1188] rotuser@rotdb LOG:  connection authenticated: identity="rotuser" method=scram-sha-256 (pg_hba.conf:119)
19:47:21.700 [1189] rotuser@rotdb LOG:  connection authenticated: identity="rotuser" method=scram-sha-256 (pg_hba.conf:119)
19:47:21.736 [1190] rotuser@rotdb LOG:  connection authenticated: identity="rotuser" method=scram-sha-256 (pg_hba.conf:119)
19:47:21.767 [1191] rotuser@rotdb LOG:  connection authenticated: identity="rotuser" method=scram-sha-256 (pg_hba.conf:119)
                    <-- ALTER ROLE rotuser PASSWORD 'pw-v2' + file write here -->
19:47:21.829 [1192] rotuser@rotdb FATAL:  password authentication failed for user "rotuser"   <- old-password control
19:47:21.865 [1193] rotuser@rotdb LOG:  connection authenticated: identity="rotuser" method=scram-sha-256 (pg_hba.conf:119)
19:47:21.896 [1194] rotuser@rotdb LOG:  connection authenticated: identity="rotuser" method=scram-sha-256 (pg_hba.conf:119)
19:47:21.930 [1195] rotuser@rotdb LOG:  connection authenticated: identity="rotuser" method=scram-sha-256 (pg_hba.conf:119)
19:47:21.961 [1196] rotuser@rotdb LOG:  connection authenticated: identity="rotuser" method=scram-sha-256 (pg_hba.conf:119)
19:47:21.990 [1197] rotuser@rotdb LOG:  connection authenticated: identity="rotuser" method=scram-sha-256 (pg_hba.conf:119)
```

(PIDs 1187-1191 and 1193-1197 are the two sets printed by the run above, so the
client-side and server-side records are of the same connections.)

Reading of that: 5 concurrent pool connections produced 5 distinct server-side
backends and exactly 5 callable invocations — per connection, not per pool.
After `ALTER ROLE rotuser PASSWORD 'pw-v2'` plus a file write, the *same pool
object in the same process* opened 5 new backends (zero PID overlap) that the
server authenticated, while a fresh connection using the old password was
rejected. A control pool built with a static string password broke on the very
next rotation.

## Q3 — redis-py asyncio

**Mechanism**, `redis/asyncio/connection.py:454-465` (installed 7.4.0), inside
`on_connect_check_health`, which `connect()` calls on every socket handshake:

```python
if self.credential_provider or (self.username or self.password):
    cred_provider = (
        self.credential_provider
        or UsernamePasswordCredentialProvider(self.username, self.password)
    )
    auth_args = await cred_provider.get_credentials_async()
```

`credential_provider` is a first-class constructor parameter
(`redis/asyncio/connection.py:185`) and a recognised URL/pool kwarg
(`:134`, `:1318`). The provider contract is `redis/credentials.py:8-22`
(`get_credentials`, `get_credentials_async`).

**Empirical run** (`exp_redis.py`, provider reads `~/exp/redispassword` on every
call):

```
$ .venv/bin/python docs/experiments/driver-credential-rotation/exp_redis.py \
    "redis://127.0.0.1:16399/0" rpw-v1
Q3a from_url(credential_provider=...)      ACCEPTED (PING succeeded)
callable invocations after 1 conn          1
server-side CLIENT ID values               [36, 37, 38, 39, 40]
server-side CLIENT LIST name=exp-redis     5
callable invocations total                 5
Q3b verdict                                ONCE PER SOCKET (5 sockets -> 5 calls)
10 PINGs on pooled connections             5 -> 5 calls
old password, fresh connection             REJECTED by server: invalid username-password pair or user is disabled.
post-rotation PING                         True
post-rotation CLIENT ID values             [42, 43, 44]
overlap with pre-rotation ids              []
post-rotation invocations                  3 -> ['rpw-v2']
Q4 redis verdict                           YES - rotation picked up, no restart
static-password client after rotation      BROKEN: invalid username-password pair or user is disabled.
callable client after 2nd rotation         True
```

Reading of that: 5 simultaneously-held pool connections were 5 distinct
server-side clients (`CLIENT ID`, and `CLIENT LIST` filtered on the client name
agrees), and the provider was invoked exactly 5 times. The "10 PINGs" line is
the important qualifier: **the unit is a socket, not a command.** Ten commands
over already-open pooled connections invoked the provider zero further times,
because redis only re-authenticates when it opens a socket. After
`CONFIG SET requirepass rpw-v2` and a file write, dropping the pool's sockets
(`await pool.disconnect()` — not a process restart) made the next commands open
new client ids that the server accepted, while the old password was rejected by
the server and a static-password client broke.

### Two constraints that matter at this repo's call sites

`exp_callsite_shapes.py`, because both call sites pass a URL that already
carries the password:

```
asyncpg: callable overrides DSN password       rotuser
asyncpg: DSN password alone                    REJECTED: password authentication failed for user "rotuser"
redis: from_url(url+password, provider)        constructed without error
redis: first command with both                 REJECTED: 'username' and 'password' cannot be passed along with 'credential_provider'...
redis: bare callable as provider               TypeError-ish: 'function' object has no attribute 'get_credentials_async'
```

1. **asyncpg tolerates the mix, redis does not.** asyncpg's DSN password is only
   consulted `if password is None` (`connect_utils.py:348`), so an explicit
   callable wins over a password embedded in the DSN — proven by connecting
   successfully through a DSN whose password is deliberately wrong. redis-py
   raises `DataError` (`redis/asyncio/connection.py:203-209`) if a password and
   a `credential_provider` are both present, so `redis_client.py:27` would have
   to strip the password out of the URL. Note it raises **on first command**,
   not at `from_url`, because the pool builds connections lazily.
2. **redis needs a `CredentialProvider`, not a function.** A bare callable
   passed as `credential_provider` fails at connect time with
   `'function' object has no attribute 'get_credentials_async'`.

## Floor versions

The locked versions are not the only ones a consumer can get, so the same
assertions were re-run under the declared floors:

```
$ ~/floorvenv/bin/python docs/experiments/driver-credential-rotation/exp_floor_versions.py \
    127.0.0.1 15499 "redis://127.0.0.1:16399/0"
asyncpg version                              0.30.0
redis version                                5.0.0
asyncpg backend PIDs / callable calls        4 / 4
redis CLIENT IDs / provider calls            4 / 4
floor versions verdict                       mechanism present in BOTH floors
```

(At redis 5.0.0 the driver calls the **sync** `get_credentials()`;
`get_credentials_async()` is a later addition. A provider implementing both is
portable across the range.)

## Q4 — verdict per driver

| Driver | Restart-free rotation? | What makes it work | What it costs |
|---|---|---|---|
| asyncpg 0.30-0.31 | **Yes** | `password=` callable, re-invoked per connection | Existing pooled connections keep the old credential until they are replaced; `pool.expire_connections()` forces the turnover. |
| redis-py 5.0-7.4 (asyncio) | **Yes** | `credential_provider=` object, `get_credentials[_async]()` per socket | Same caveat, plus: the password must be removed from the URL, and existing sockets must be dropped (`pool.disconnect()`) for rotation to take effect promptly. |

For both, "picked up by new connections" is exactly what happens; already-open
connections are unaffected until they reconnect, which is the expected and
correct behaviour for a rotation (the server does not invalidate live sessions
either).

## What could NOT be verified, and why

- **Nothing was run against the repo's own stack.** No Docker, so
  `just test-stack`, the testcontainers fallback, and TimescaleDB specifically
  were all unavailable (proof above). The servers used are stock PostgreSQL
  16.2 and Redis 6.2.14, not this project's `timescale/timescaledb:2.29.2-pg16`
  and its Redis image. Authentication is core server behaviour and does not
  differ by image, but that inference is not something this run measured.
- **Not tested against the real call sites.** Production code was deliberately
  untouched, so `_wiring_db.py:41` and `redis_client.py:27` were *modelled*
  (`exp_callsite_shapes.py` reproduces their argument shapes) rather than
  modified and exercised. Whether the repo's actual `settings.redis_url` /
  `db_url` plumbing can cleanly surrender its embedded password is a design
  question this experiment did not answer.
- **No TLS, no cluster, no Sentinel.** `ConnectionPool` only; not
  `RedisCluster`, not `Sentinel`, not `BlockingConnectionPool`, all of which
  build connections through their own paths. asyncpg was tested over TCP with
  scram-sha-256 only — not md5, not SSL/`sslpassword`.
- **No concurrency race testing.** Rotation was performed while the process was
  idle between assertions. What happens to an in-flight connection attempt that
  starts before the rotation and finishes after it was not measured.
- **redis-py's `StreamingCredentialProvider` re-auth path was not exercised.**
  `redis/credentials.py:24-46` offers a push-based provider that can re-auth
  *live* connections; only the pull-per-socket path was tested.
- **Not measured: cost.** Every new connection now performs whatever work the
  provider does (here, a file read). Under connection churn that is a per-connect
  syscall, unmeasured here.
