# Plan: brokered credentials and an egress allowlist for E2B sandboxes (#1919)

**Status:** draft for review, 2026-10-27. Step I of
`docs/research/2026-10-08-remote-executor-e2b.md` §5. Epic #1612, umbrella #350.

**Read on:** `origin/main` at `e8fa918cf` (after #2078). agentic-workspace (AW) pinned at
`fb696fd8`; #2149 (open) bumps it to `896449c5`, which carries AW#104 (reattach, pause/resume).
E2B SDK facts are from the `e2b==2.52.0` source (`e2b/sandbox/sandbox_api.py`), the version AW
pins. `file:line` citations drift as PRs land.

**This plan does not redesign the broker.** The broker is #1735's, designed in
`docs/plans/20261014_credential-broker.md` (D1-D13, PRs 1-9) with owner rulings in
`docs/plans/20261014_credential-broker-owner-decisions.md` (H1/H2 ALLOW, H4 recommendation).
#1919 is what an E2B sandbox needs on top of it: delivery, reachability, egress, the policy that
lets a brokered executor claim agent work, and the storage of the E2B writer's reattach token.

---

## 1. Goal and acceptance (from #1919)

**Goal.** Real Claude runs go to E2B. The sandbox holds only per-workspace broker capabilities,
never an upstream credential, and can reach only an allowlist. The `workload = 'scripted'`
clause is lifted for brokered executors.

**Acceptance (as written in #1919, made concrete):**

1. A brokered run on E2B completes with **no upstream credential in the sandbox**, per D's scan
   (`test_1914_no_credentials_leaks_nothing.py`, lifted into the Credential Tripwire by #1918
   PR 3) on every host-to-sandbox channel, plus #1735 D13's canary scan at phase boundaries.
2. From inside that sandbox, a request to a host **outside the allowlist fails** (connection
   refused or reset by E2B, not an HTTP error from some server).
3. **Negative control:** the same run with deny-all dropped from the sandbox network config
   makes the off-allowlist request succeed, so the test fails.
4. Added here, from the ruling on #2161: no reattach token in any event, log line or spool row.
   Negative control: storing it in plaintext fails the row-bytes scan.

Acceptance 2 and 3 need real E2B (CI has no key, by owner ruling). CI proves the shape against
the `SandboxDouble` by asserting the network body the provider sends (§5, AW-1).

---

## 2. What is on main, and what E2B gives us (verified)

| Fact | Evidence |
|---|---|
| The policy port has `HostCredentials` and `NoCredentials`; one property, `supplies_credentials` | `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workspace_credential_policy.py` |
| `BackendKit.e2b` is always `NO_CREDENTIALS` | `packages/syn-adapters/src/syn_adapters/workspace_backends/backend_kit.py` (`e2b`) |
| The claim clause is `supplies_credentials OR workload='scripted'` | `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py` (`can_run`); memory twin `execution_runs/memory.py:415` |
| `supplies_credentials` also gates the session-store token, git renewal, sidecar and image allowlist | `workspace_backends/agentic/adapter.py:268`, `service/managed_workspace.py:431`, `service/workspace_service.py:198`, `backend_kit.py` (`_require_permitted`) |
| git/gh presentation under the broker exists (S2 merged, #1929) | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/github_presentation.py` |
| The grant store, injector rewrite, presenters and remote listener (#1735 PRs 2-8) are **not** on main | no `BrokerGrant` in `packages/`; `docker/token-injector/token_injector.py` is host-keyed |
| AW's E2B provider refuses `limits.network=False` and workspace credential bindings, and passes no network config to E2B | AW `providers/e2b.py` (`create`), at AW `origin/main` |
| AW's E2B operations deliver launch credentials in the command's `envs` only, never argv, redacted in the spool | AW `providers/e2b_operations.py` module docstring |
| A reattach token is minted per operation by the starting instance; only its digest enters the sandbox; with the ref it authorizes `status` and `cancel` (not `observe`) | AW `providers/e2b_operations.py` (`reattach_token`, `reattach`); `providers/capabilities.py` (`SupportsOperationReattach`) |
| Recovery's writer stop is a FIXME waiting for that token | `packages/syn-adapters/src/syn_adapters/session_inventory/sandbox_recovery.py` (`stop_writers`, `writers_stopped`, `remove`, all `FIXME(#1916)`) |
| The E2B executor refuses to start outside test/offline | `apps/syn-api/src/syn_api/services/execution_host_runner.py` (`_refuse_unverified_e2b_reap`, `TODO(#1916)`) |
| The spool row is a projection, rebuilt from events | `packages/syn-domain/src/syn_domain/contexts/agent_sessions/ports/SessionCaptureSpoolPort.py` (`project`: "Idempotent projection only") |

**E2B network controls in `e2b==2.52.0`** (`AsyncSandbox.create(..., network=, iam=, allow_internet_access=)`):

- `network.deny_out` / `allow_out`: lists of CIDRs, IPs or hostnames. `e2b.ALL_TRAFFIC` is
  `"0.0.0.0/0"`. Deny-all plus an allowlist is `deny_out=[ALL_TRAFFIC], allow_out=[...]`.
- `network.rules`: per-domain header transforms on egress HTTP/HTTPS, applied by E2B's egress
  proxy. A host in `rules` must also be in `allow_out`. Research §2 records transforms as public
  beta (2026-10-08).
- `network.egress_proxy`: a SOCKS5 proxy **we** operate; E2B tunnels the sandbox's outbound TCP
  through it on the host, after filtering, fail-closed. The sandbox cannot see it. **UDP (DNS,
  QUIC) is not tunneled.**
- `iam.tokens`: workload identity, `token_type="JWT-SVID"` with an audience. A `rules` transform
  can inject `ctx.iam.tokens[name]` as a header; the docstring says "the secret itself never
  leaves the platform".
- `update_network` replaces the whole config atomically; an update that omits a field clears it.

---

## 3. Design

### 3.1 `BrokeredCredentials`: the third policy, and lifting the `workload` clause

`supplies_credentials` today means two things: "host credentials enter the workspace" and "this
backend can run agent work". Brokered splits them: no host credential enters, but agent work runs.

- Add to the `WorkspaceCredentialPolicy` Protocol: `runs_agent_work: bool` and
  `delivery: CredentialDelivery` (`HOST | BROKERED | NONE`, a `StrEnum` in the orchestration
  context).
- `BrokeredCredentials`: `supplies_credentials = False`, `runs_agent_work = True`,
  `delivery = BROKERED`. Every existing `supplies_credentials` reader keeps its meaning: no
  session-store token, no host renewal script, no sidecar join. The brokered sources (grant issue,
  presenters, `github_presentation`) are new branches on `delivery`, never on the old bool.
- `admit()` refuses a phase whose credential classes have no broker route or presenter yet (for
  example Codex before #1735 S1 passes for it), before `create_workspace`.
- **The pool column.** `executor_pools.supplies_credentials` keeps its name for now but is
  written from `runs_agent_work`; `can_run` becomes `(pool.runs_agent_work OR
  r.workload='scripted')` via a new column `runs_agent_work` (`ADD COLUMN IF NOT EXISTS`,
  backfilled from the old one) so the SQL does not lie. The old column is dropped in a later PR
  (D2).
- `BackendKit.e2b(template, *, policy=...)`. `SYN_E2B_CREDENTIAL_POLICY = none | brokered`,
  default `none`. Under `brokered`, the D5 stub-only rule of #1918 does not apply: the kit runs
  the agent template (#2150's nested-Docker template, per #1918 D5).

**Boundary (CLAUDE.md test).** What a capability is, which classes a phase gets, the allowlist
contents and grant lifetime change when **we** decide what a credential is: syn137. How Claude or
Codex is told to use a base URL and a capability changes when Anthropic or OpenAI ship a CLI:
AW presenters (#1735 D6, `HarnessCredentialPresenter`). How an E2B sandbox's network is
configured changes when E2B ships an SDK: AW provider (AW-1 below). syn137 defines one
provider-neutral `EgressPolicy` contract; AW translates it.

### 3.2 How the agent reaches Claude and GitHub without the upstream secret

Central broker (#1735 D1, H5 default): the existing Envoy plus a grant-keyed token injector on
the control plane. Upstream secrets live only there (#1735 D3).

```
E2B sandbox --HTTPS + capability--> public broker hostname (TLS listener, #1735 PR 8)
            --ext_authz--> token injector (Redis grant lookup, per request)
            --upstream TLS + real credential--> api.anthropic.com / github.com
```

- **Location: control plane, not per sandbox.** A per-sandbox broker would put the upstream
  secret on E2B's host, which is the residency question the research rejected ("option A",
  decision 6). There is no owned box on E2B, so #1735's H4 recommendation (a secret-free box
  Envoy holding a per-box mTLS cert) **does not apply**: §3.2 of the owner-decisions doc scopes
  it to owned boxes. E2B is a new case for H4 (D4).
- **Sandbox to broker authentication.** The per-workspace, per-class capability (#1735 D2:
  32 bytes of host entropy, broker stores only `sha256(wire)`, grant bound to `execution_id`,
  `workspace_id`, `token_type`, `expires_at`). It is delivered:
  - to the agent process through AW operation `credential_bindings` (envs only, redacted);
  - to git and gh as capability-bearing files written by `github_presentation` through
    `write_bytes`. These files hold capabilities only, which the Tripwire allows and an upstream
    value would trip.
- **Binding the capability to the sandbox (D3).** A bearer exfiltrated through an allowed host
  is replayable from anywhere until its deadline. Three options:
  - (a) capability only, plus a tight TTL. Meets #1919's acceptance. Default for the first slice.
  - (b) E2B workload identity: an `iam` JWT-SVID with audience `syn137-broker`, injected by an
    E2B `rules` transform on the broker hostname. The injector verifies it and checks that its
    subject is the sandbox the grant was issued for. The token never enters the sandbox.
    **Unclear:** issuer, JWKS location, which claims name the sandbox, plan availability, beta
    status. Settled by spike S-E1.
  - (c) `egress_proxy`: all sandbox TCP tunnels through a SOCKS5 proxy we run, with per-sandbox
    SOCKS credentials held by E2B. The proxy knows the sandbox and can bind grants to it. It is a
    new public TCP service (owner choice) and DNS is not tunneled.
  Recommended: (a) now, (b) if S-E1 confirms it, (c) only if (b) is unavailable.
- **gh's DNS trick needs re-proving on E2B.** S2 made gh work by resolving `github.com` and
  `api.github.com` to the broker and trusting a broker CA (`github_presentation.py` docstring).
  **Unclear:** whether E2B's hostname filter matches the TLS SNI, the Host header or the DNS
  answer. If it matches SNI, a `github.com` SNI aimed at the broker's IP is judged as
  `github.com`. S-E1 settles it. The fallback is allowing the broker by IP or CIDR.
- **Revocation.**
  - Normal teardown: `BrokerGrantService.revoke_workspace(workspace_id)` in
    `create_workspace`'s `finally` (#1735 D10 step 7), on E2B as on Docker.
  - Cancel: same path. The cancel ends the operation, then the `finally` revokes.
  - Executor death: grants die at `expires_at` (deadline, plus the interrupt budget for git,
    #1735 D9). **Also**, `E2BRunReaper.reap` (`workspace_backends/e2b/recovery_kit.py`) revokes
    every grant of `(executor_id, execution_id)` **before** the kill. That needs an index
    `syn:broker-exec:<execution_id>` beside #1735 D11's per-workspace index, because the reaper
    knows the execution, not the workspace ids (D6).
  - Revocation is effective on the next request (per-request Redis lookup, #1735 D11). In-flight
    streams run to the 300 s route timeout (#1735 H3, unchanged).

### 3.3 Egress allowlist

- **Contract.** `EgressPolicy` (frozen Pydantic, `extra="forbid"`): `deny_all: bool`,
  `allow_hosts: tuple[str, ...]`, `allow_cidrs: tuple[str, ...]`. syn137 builds it from settings
  (`SYN_E2B_EGRESS_ALLOW`), never per run. The same type is what #1794 option 1 would use for
  local `agent-net`, so there is one allowlist vocabulary.
- **E2B translation (AW).** `deny_out=[ALL_TRAFFIC]`, `allow_out=allow_hosts + allow_cidrs`, at
  `create`. AW never calls `update_network`: a partial update clears fields (SDK docstring), so an
  egress change mid-run is refused, not attempted.
- **Default contents.** The broker hostname(s) only. Package registries and direct `github.com`
  are owner choices (O4). Dropping `github.com` follows #1735 D5, which records it as a
  deliberate change from research decision 6.
- **Fail closed.** A provider that cannot apply `deny_all` (an open-source `e2b-dev/runtime`
  deployment, a plan without the feature) refuses `create`. It never creates an open sandbox.
  `BrokeredCredentials` refuses a kit whose `EgressPolicy.deny_all` is false (D5).
- **Relationship to #1794.** #1794 is local Docker `agent-net` (`agent-net: null` in
  `docker/docker-compose.syntropic137.yaml`). This plan does not change it. Remote egress is
  stricter than local until #1794 is decided; that asymmetry is stated in `docs/deployment/e2b.md`
  by slice P4.
- **Unclear:** whether `deny_out=[ALL_TRAFFIC]` blocks DNS (UDP 53). If not, DNS is an
  exfiltration channel. S-E1 measures it; if open, it is recorded as a stated limit.

---

## 4. The E2B writer's reattach token (ruled a credential)

**What it is.** A random secret the AW `E2BOperations` instance mints per launched operation.
With the `OperationRef` and E2B API access, it lets a fresh worker `reattach` and then `status`
and `cancel` the agent writer: exactly what `RecoverySandbox.stop_writers` and
`RecoverySandboxes.writers_stopped` need. It never enters the sandbox (only a digest does).

**Ruled:** never in the event store, logs or a spool row in plaintext. The spool row is a
projection rebuilt from events, so it **cannot** hold a value that events must not hold. The token
needs its own store, written by infrastructure, not by a projector.

### 4.1 Options

| Option | Restart-safe | New dependency | Verdict |
|---|---|---|---|
| **A. Postgres table, AES-256-GCM encrypted value** | yes (same Postgres as the run queue and spools) | none (`cryptography` is already a syn-adapters dependency) | **recommended** |
| B. Redis beside broker grants, with TTL | only with AOF (#1735 H6 open); paused sandboxes have no TTL | none | rejected: a paused spool may outlive any TTL |
| C. Derive it: `HMAC(K, operation_id)` | yes, nothing stored | AW contract change (caller-supplied token at `start`) | follow-up: removes the crash window in 4.3, but K is a master key over every operation |
| D. In the sandbox or E2B metadata | n/a | none | rejected: the workload or any API-key holder reads it |
| E. External secrets manager | yes | a new external service | owner choice only (O6) |

### 4.2 Recommended storage (A)

- Table `remote_operation_secrets` in the session-inventory database (`session_inventory/schema.sql`),
  **not** a projection: `sandbox_id`, `session_id`, `executor_id`, `operation_ref`
  (plaintext JSON; an id is not a secret), `key_id`, `nonce`, `ciphertext`, `created_at`,
  `delete_after`.
- AAD = `sandbox_id | operation_id | executor_id`. A row copied onto another sandbox's key
  fails to decrypt.
- The key ring is read at use from a file (ADR-070 D1): `SYN_REMOTE_SECRET_KEYS_FILE`, a JSON
  list of `{key_id, key}`, the first one current. It is a `SecretStr`, never in the environment.
- Port `RemoteOperationSecretStore` (`put`, `get`, `delete`) in syn-adapters, with
  `PostgresRemoteOperationSecretStore` and `InMemoryRemoteOperationSecretStore(InMemoryAdapter)`.
  Production wiring with `SYN_E2B_ENABLED` and no key file or no database **refuses to start**
  (ADR-060; no in-memory fallback).
- The value is a `SecretStr` from `get` to `reattach`. It is never logged, and the store logs
  only ids.

### 4.3 Lifecycle

1. **Write.** The E2B executor calls `reattach_token(ref)` right after `start` returns and `put`s
   the row **before** it consumes the stream. If `put` fails, it cancels the operation in-process
   (it still owns it) and fails the phase.
2. **Crash window.** A crash between `start` and `put` leaves no token. Recovery then cannot
   confirm writers, so `exclusive` stays False and `remove` keeps the sandbox paused, never
   killed (today's fail-closed path). It alerts with the sandbox id. Option C closes this window.
3. **Read.** The production `RecoverySandboxes` adapter (below) reads the row for the spool's
   `(sandbox_id, session_id)` and checks `executor_id` against the spool row.
4. **Delete.** After the spool is `mark_drained` and the kill is confirmed (release), or when the
   starting executor settles the operation and its spool drains normally. A sweeper deletes rows
   whose sandbox `lookup` is confirmed gone (by recorded id, not by listing).
5. **Rotation.** Prepend a new key, run `just rotate-remote-secrets` (a tested Python script;
   it re-encrypts every row under the current key), then remove the old key. This is independent
   of E2B key rotation (`docs/deployment/e2b.md` "Rotating the E2B key"): recovery needs **both**
   the E2B key for the scope and this key for the token. P2 adds a paragraph there saying so.

### 4.4 How recovery uses it (closes the `FIXME(#1916)` gap)

`E2BRecoverySandboxes` satisfies `RecoverySandboxes` (`session_inventory/sandbox_recovery.py`):

- `resume`: `E2BRecoveryKit` attach with the ownership check, then AW `SupportsWorkspaceSuspend.resume`.
- `stop_writers` / `writers_stopped`: `get` the token, AW `SupportsOperationReattach.reattach(ref,
  token)`, then `cancel` and `status`. A missing row, `unknown_operation` or
  `provider_unavailable` means False.
- `pause` and `kill`: AW suspend, Recovery Kit kill.
- Wired as `remote_recovery={"e2b": SandboxSpoolRecovery(E2BRecoverySandboxes(...))}`
  (`session_inventory/runtime.py`), only on executors holding the E2B Recovery Kit
  (`SYN_E2B_RECOVERY_API_KEY`) **and** the key ring.
- It needs the #2149 pin (AW `896449c5`). The adapter is #1916 scope; this plan supplies its
  store. Removing `_refuse_unverified_e2b_reap` stays with #1916 (confirm by recorded id).

---

## 5. Threat model

| Threat | Control | Residual |
|---|---|---|
| Prompt-injected agent sends an upstream credential off-box | None is in the sandbox: Tripwire refuses the call, #1735 D12 `SendGuard`, canary scan | Scan limits (#1735 D13) |
| Agent exfiltrates a capability through an allowed host | Deny-all egress; per-class capability; TTL = deadline; revoke on teardown and reap | Replay until revoke unless D3 (b) or (c) binds it to the sandbox |
| Agent uses the broker as an open proxy | Injector routes only the `UPSTREAM_ROUTES` table (#1735 PR 4) | none |
| Exfiltration through registries or direct github.com | Not on the default allowlist (O4) | Present if the owner allows them |
| DNS exfiltration | **Unclear** (S-E1) | Stated limit if UDP 53 is open |
| A database dump leaks reattach tokens | AES-GCM with AAD; key in a separate file | The key holder plus the E2B key can cancel writers, nothing more |
| E2B (vendor) sees traffic | It already hosts the VM and memory. With D3 (b) it terminates TLS to the broker host | Owner choice O3 |
| Brute force or DoS on the public broker | 32-byte capabilities; ingress rate limit | Fail-closed broker means DoS stops runs |
| Executor crashes holding live grants | Reaper revokes by execution index; TTL backstop | Until reap, bounded by the deadline |

### Failure modes

| Failure | Handling |
|---|---|
| Broker unreachable from E2B | Model and git calls fail; the phase fails. Never a fallback to host credentials |
| Redis down | Injector denies (fail closed, #1735 PR 4) |
| E2B refuses the network config | `create` fails and is retried as a create failure (Outage Breaker counts it). No open sandbox |
| Reattach-token `put` fails | Cancel in-process, fail the phase (4.3 step 1) |
| Crash between `start` and `put` | Sandbox stays paused; alert (4.3 step 2) |
| Key ring missing on a recovery executor | It does not register the E2B remote recovery; the spool waits for one that has it (as for the Recovery Kit) |
| Grant expires mid-phase | Bounded to the deadline, so only after the phase is already over its time; git keeps the interrupt grace (#1735 D9) |

**Restart safety (ADR-060).** Grants are in Redis (durable store, #1735 D11), reattach tokens in
Postgres, the policy is fixed at wiring. Every double inherits `InMemoryAdapter`. Production
refuses to start with E2B brokered and no Redis, no key ring or no database. Nothing needed after
a restart is held only in process memory.

---

## 6. Slices

Each PR carries a test that fails when its change is reverted and a negative control.
`.mutations/` per syn137 PR, as for #1918.

| Slice | Repo | Content | Depends on |
|---|---|---|---|
| **S-E1** spike | syn137 (local, real E2B) | `scripts/e2b_egress_probe.py`: deny-all plus one allowed host; `curl` to it passes, to another fails; DNS lookup of an off-list name; `/etc/hosts` override plus SNI to the broker; IAM JWT-SVID claims and JWKS. Results written into this plan | owner spend (O1) |
| **AW-1** | AW | `EgressPolicy` on `WorkspaceConfig`; E2B `create` passes `network`; refuses when `deny_all` cannot apply; `limits.network=False` maps to deny-all; no `update_network`. Python only: a submodule bump, no image release | none |
| **P1** | syn137 | `CredentialDelivery`, `runs_agent_work`, `BrokeredCredentials` (refuses every phase until P4 wires it), `runs_agent_work` pool column, `can_run` | none |
| **P2** | syn137 | `RemoteOperationSecretStore` (Postgres + AES-GCM, in-memory double), key ring setting, rotation script, executor `put` after launch, docs | #2149 (for `reattach_token` on the pinned provider) |
| **P3** | syn137 (#1916) | `E2BRecoverySandboxes`, wired in `runtime.py` | P2, #2149, #2161 |
| **P4** | syn137 | E2B brokered wiring: kit policy, `EgressPolicy` from settings, capability delivery, reap-time revoke, execution index | #1735 PRs 2-5 and 8, AW-1, P1 |
| **P5** | syn137 (owner run) | `just e2b-brokered-run`: acceptance 1-3 live; flip nothing by default | P4, H (#1918) |

### Exit tests and negative controls

- **AW-1.** `test_a_deny_all_policy_sends_deny_out_all_traffic_and_the_allowlist` (fake SDK client
  records the create body). Negative control: dropping `deny_out` from the translation fails it.
  `test_create_refuses_when_deny_all_cannot_apply`. Live (`test_e2b_live.py`): off-list `curl`
  fails, on-list succeeds.
- **P1.** `test_a_brokered_pool_claims_an_agent_row` (Postgres) and its memory twin;
  `test_a_no_credentials_pool_still_claims_only_scripted_rows`. Negative control: `can_run`
  reverted to `supplies_credentials` makes the brokered claim test fail.
  `test_brokered_keeps_every_supplies_credentials_reader_closed`: no session-store token, no
  renewal script, no sidecar.
- **P2.** `test_no_reattach_token_in_any_event_log_line_or_spool_row` (scans the event store, the
  captured log records and the raw `session_capture_spools` and `remote_operation_secrets` bytes for the
  token). Negative control: a store that writes plaintext fails it.
  `test_a_row_moved_to_another_sandbox_does_not_decrypt` (AAD).
  `test_rotation_re_encrypts_and_the_old_key_can_be_removed`.
  `test_production_wiring_refuses_e2b_without_a_key_ring`.
  `test_a_failed_put_cancels_the_operation_and_fails_the_phase`.
- **P3.** #1916's live-writer test against `SandboxDouble` with a fresh worker. Negative control:
  an adapter that skips `reattach` gets `unknown_operation`, `exclusive` is False, the release
  never happens and the test fails.
- **P4.** `test_a_brokered_e2b_provision_sends_capabilities_and_no_upstream_value` (Tripwire on
  every channel, real `BrokerGrantService` with the in-memory store).
  `test_reap_revokes_every_grant_of_the_execution_before_kill`. Negative control: removing the
  reap-time revoke leaves a grant that `authorize` accepts, and the test fails.
  `test_a_brokered_kit_without_deny_all_refuses_to_construct`.
- **P5 (owner run).** A real Claude phase on E2B, brokered, with #1735 D13 scans `clean` at every
  boundary; an off-list `curl` from inside fails; `--negative-control` builds the sandbox with
  `deny_all=false` and the script must report the off-list request **succeeded**, exiting
  non-zero. The negative-control switch is refused unless `APP_ENVIRONMENT=development` (as #1918
  D7).

### What lands where

- **AW:** `EgressPolicy` translation to E2B (AW-1); harness presenters (#1735 PR 6). Neither
  needs a new image, so no `release` to `PINNED_DIGESTS` round trip, unless S-E1 forces a CA or
  `/etc/hosts` change into the template (then #2150's template rebuild carries it).
- **syn137:** the policy, the allowlist contents, grants and revocation, the secret store, the
  recovery adapter, the acceptance script.

---

## 7. Decisions (recommended defaults)

| # | Decision | Default (★) | Alternative |
|---|---|---|---|
| D1 | Scope of #1919 | ★ E2B delivery on top of #1735's broker; no second broker | Vendor secret injection (O3) |
| D2 | Lifting the `workload` clause | ★ New `runs_agent_work` on the policy and the pool; old column dropped later | Reuse `supplies_credentials` (it would lie) |
| D3 | Binding a capability to its sandbox | ★ (a) capability + TTL now; (b) E2B JWT-SVID if S-E1 confirms | (c) our SOCKS5 egress proxy |
| D4 | Broker location for E2B | ★ Central, control plane, public TLS hostname (#1735 PR 8) | Per-sandbox broker (puts the secret on E2B) |
| D5 | Brokered without deny-all | ★ Refused at kit construction | Allow with a warning |
| D6 | Revocation on executor death | ★ Reaper revokes by an execution index, before kill; TTL backstop | TTL only |
| D7 | Egress allowlist default | ★ Broker hostname(s) only | Plus registries, plus github.com (O4) |
| D8 | Reattach-token store | ★ Postgres, AES-256-GCM, AAD, key ring from file | HMAC derivation (needs AW change), Redis |
| D9 | Reattach-token write failure | ★ Cancel in-process and fail the phase | Continue without recovery |
| D10 | Policy selection | ★ `SYN_E2B_CREDENTIAL_POLICY=none` default; `brokered` only after P5 | On by default once P4 merges |
| D11 | One allowlist vocabulary | ★ `EgressPolicy` shared with #1794 option 1 | Per-backend formats |

## 8. Owner choices

Not ruled by the orchestrator: spend, the E2B account, data leaving our systems, template
deletion, any new external service.

1. **O1. E2B spend** for S-E1 and P5 (a few short sandboxes each), on the owner's key, with any cap.
2. **O2. Public broker ingress.** A Cloudflare-tunnel hostname exposing the broker to the
   internet (new external exposure). E2B cannot reach the tailnet.
3. **O3. Data at E2B.** E2B already sees code and prompts. D3 (b) also means E2B terminates TLS to
   our broker hostname and sees capabilities. Vendor-side secret injection (E2B holds upstream
   credentials) stays rejected unless the owner chooses it.
4. **O4. Allowlist contents.** Package registries (agents cannot install without them; an
   exfiltration channel with an attacker's token) and direct `github.com` (#1735 D5 drops it).
5. **O5. Claude Max OAuth on a vendor sandbox.** H1 ALLOW (2026-10-14) was recorded for remote
   workspaces; confirm it covers a third party's VM, not only owned boxes.
6. **O6. E2B plan tier** for `rules` transforms, IAM and `egress_proxy`, if S-E1 shows a tier gate;
   or an external secrets manager for 4.1 option E.
7. **O7. SOCKS5 egress proxy** (D3 (c)), a new public service, only if (b) is unavailable.
8. **O8. Templates** created by S-E1: keep, or delete after the run.

## 9. Unclear

- **Unclear:** how E2B matches hostnames in `allow_out` (SNI, Host header or DNS), and so whether
  S2's gh DNS override works under deny-all. S-E1.
- **Unclear:** whether deny-all blocks UDP DNS. S-E1.
- **Unclear:** E2B JWT-SVID issuer, JWKS, the claim naming the sandbox, tier and beta status.
  S-E1.
- **Unclear:** whether H4 (owned-box mTLS) has been approved; it does not cover E2B either way
  (D4). Needs a ruling on #1735.
- **Unclear:** E2B egress IP ranges, if the broker ingress wants a source allowlist.

## 10. Out of scope

- The broker itself (#1735 PRs 2-9), local `agent-net` egress (#1794), the E2B spool write side
  (#2161), confirm-by-recorded-id reaps (#1916), Codex on E2B until #1735 S1 passes for it.
