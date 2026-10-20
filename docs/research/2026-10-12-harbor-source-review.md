# Harbor v0.24.0 deep source review (2026-10-12)

Repo: https://github.com/harbor-framework/harbor at `b53b8134e1241686dca7759af188f987ecc48e8b` (stable v0.24.0). Commit dated 2026-10-04; GitHub release published 2026-10-05. Read-only source inspection. No Harbor tests or live sandboxes executed. Source paths below refer to this commit. [Design synthesis and Syn/APSS gap matrix](2026-10-12-harbor-opensandbox-runtime-design.md).

## Main judgment

Harbor demonstrates a common, practical provider adapter architecture. Reuse its separation of environment from agent and its explicit capabilities/preflight validation. Do not copy BaseEnvironment wholesale as a distributed production runtime contract: it is an evaluation framework abstraction with local paths, buffered results, process-local ownership, and backend-dependent cancellation/retention/output semantics. Harbor already uses OpenSandbox as one environment backend, so these references are complementary layers rather than competing complete platforms.

## Architecture and reusable patterns

| Concern | Proven source behavior | Reuse implication |
|---|---|---|
| Common operations | Async start/stop, upload_file/upload_dir, download_file/download_dir, exec, optional service operations. `environments/base.py:959-1009,1186-1205,1257-1385` | Small common provider surface plus optional profiles; keep workflow policy outside it. |
| Factory | Lazy SDK imports and registry by EnvironmentType; custom imported provider support. `environments/factory.py:28-188,216-339` | Dependency isolation and plugin registry; configure backend once at pool bootstrap. |
| Three identities | ephemeral `session_id`, durable UUID `context_id`, content hash `environment_id`. `base.py:117-129,258-270` | Distinguish logical run, provider resource, immutable environment content and attempt. |
| Content-addressed builds | Deterministic SHA256 sorted relative filenames plus lengths and bytes, ignores `.git`, `__pycache__`, `.DS_Store`, skips symlinks. `definition.py:75-140`; E2B alias uses first12 chars `e2b.py:103-108` | Cache immutable environments; include image digest, build options, arch and resources when backend embeds them. See gotcha below. |
| Explicit feature capabilities | Typed feature flags stream/GPU/TPU/network subtype/dynamic network/OS/mount/compose. `capabilities.py:12-66` | Requirement matching, never assume a vendor name implies a feature. |
| Exact network enforcement | Construction validates offline/allowlist and exact hostname/wildcard/IP/CIDR shapes; unsupported requests raise before start. Runtime switches validate before applying and update local state only after success. `base.py:816-912` | Fail closed on security requirements; desired and effective policy recorded separately. |
| Resource semantics | Separate resource capabilities for CPU/memory request versus limit, with auto/limit/request/guarantee/ignore modes. Docker and OpenSandbox limits; E2B requests. `capabilities.py:69-80`, `base.py:342-428`, `models/trial/config.py:55-61` | Do not pretend `2 CPUs` means both reservation and hard cap. Explicit enforcement intent plus effective allocation. |
| Scoped overlays | ContextVars isolate output callbacks and env overlays between simultaneous asyncio tasks on same environment. `base.py:242-248,499-555` | Avoid shared mutable callback/environment context when multiple commands run together. |
| Separate phase policies | Agent/verifier can have different network policies and shared or separate workspaces. `base.py:154-198,891-906`, `trial/trial.py:867-1018` | Policy belongs to launch/phase requirements, not hardcoded provider assumptions. |
| Lifecycle cleanup | Trial shields stop against asyncio cancellation; OpenSandbox cleans partially created resources on readiness failure. `trial/trial.py:1871-1891`, `opensandbox.py:414-449` | Persist resource identity before readiness; teardown and reconciliation are first-class work. |

## Provider comparison

| Dimension | Docker | E2B | OpenSandbox adapter |
|---|---|---|---|
| Provisioning | Compose project per session; content-addressed local build; `docker/docker.py:700-755,1005-1115` | Template build cache then AsyncSandbox.create; `e2b.py:175-269` | Prebuilt single-container image only; Compose rejected; `opensandbox.py:177-202,382-432` |
| CPU/RAM | Hard limits | Requests passed when template builds | Hard limits mapped into resource map; no per-sandbox storage mapping |
| Networking | Offline/allowlist only when egress-control enabled; feature flags reflect that | Hostnames/wildcards/IPv4 exact addresses; no IPv6 or CIDR; runtime switching | Current Harbor adapter offline/public only; no allowlist/dynamic advertised, even if underlying OpenSandbox supports more |
| Exec | Shell command string wrapped in bash/cmd for main, sh sidecar | Background command handle then wait | Foreground SDK execution stream aggregated into result |
| Output | Compose redirects stderr into stdout; optional callback receives stdout lines; final result retained | Separate stdout/stderr result; no forwarding of BaseEnvironment callback in this adapter | Separate stdout/stderr result; no BaseEnvironment callback forwarding in this adapter |
| Retention | stop/delete/keep_containers semantics; default teardown can remove volumes | stop(delete=False) still kills, intentionally ephemeral | stop(delete=False) closes client and leaves remote sandbox until TTL |
| Instance reconnect | Optional persisted non-secret StreamHandle for SSH mode | No generic reconnect/attach method in this adapter | No generic reconnect/attach method in this adapter |

Sources: [Docker capabilities](https://github.com/harbor-framework/harbor/blob/b53b8134e1241686dca7759af188f987ecc48e8b/src/harbor/environments/docker/docker.py#L316), [Docker execution](https://github.com/harbor-framework/harbor/blob/b53b8134e1241686dca7759af188f987ecc48e8b/src/harbor/environments/docker/docker.py#L700), [E2B](https://github.com/harbor-framework/harbor/blob/b53b8134e1241686dca7759af188f987ecc48e8b/src/harbor/environments/e2b.py#L66), [OpenSandbox](https://github.com/harbor-framework/harbor/blob/b53b8134e1241686dca7759af188f987ecc48e8b/src/harbor/environments/opensandbox.py#L65).

## Execution safety and recovery

E2B is particularly useful evidence for retry classification. `_dispatch_command` retries only connection establishment / pool timeout / 429, all intended to prove command was not dispatched. Once a PID/handle exists, `handle.wait()` transport errors propagate; no redispatch. Nonzero process exit is returned as a result, not retried as an infrastructure exception. `e2b.py:46-56,432-508`. Unit cases explicitly cover post-dispatch failure not redispatched, nonzero exit, connection retry and exclusion of read/write errors (`tests/unit/environments/test_e2b.py:236-304`). Inference: Syn needs durable command ids and outcome-unknown state because simply letting an error propagate does not reconcile the surviving process.

OpenSandbox adapter creates with health-check bypass to obtain/log sandbox identity before readiness, then polls terminal status and health itself. Poll default 2s versus SDK200ms, with comments explicitly explaining concurrent proxy429 amplification. Health probe transient errors remain within the readiness loop, avoiding creation of a second sandbox. Readiness failure/cancellation kills and closes best effort. `opensandbox.py:376-501`. Mock tests cover timeout kill, terminal failures and no-recreation on transient health failure (`tests/unit/environments/test_opensandbox.py:676-851`). A transport error during create before a handle returns still needs provider-side idempotency or fleet reconciliation; this code alone does not prove exactly-once creation.

The common interface has no explicit command status/get/cancel/reconnect contract. Optional `connect_ssh` resolves persisted StreamHandle without provisioning/deleting, but only applies to SSH-capable configurations (`base.py:528-543`, factory.py:218-222). Do not conflate that with provider-independent resume/reconciliation.

Docker streamed path terminates the LOCAL Compose subprocess on timeout/cancellation, with terminate then kill5s later (`docker/docker.py:827-897`). This does not prove remote container process-group termination. Buffered path only catches TimeoutError, streamed path additionally catches BaseException. A production cancellation conformance test must inspect process death inside sandbox, not infer it from await cancellation.

## Scaling and durable ownership

`TrialQueue` bounds local trials using asyncio.Semaphore, plus per-agent concurrency-key semaphores with hook cleanup (`trial/queue.py:20-49,111-192,239-267`). No distributed lease/fencing in that queue. Trial retry constructs a new Trial, reruns it, removes prior trial directory, then exponential backoff (`queue.py:195-237`). Default max_retries0; exclusions include timeout/auth/refusal/usage errors (`models/job/config.py:291-321`). Job resume reads local config/result/trial directories and reconciles already-completed trial configs (`job.py:258-381`). It is useful evaluation resume, not evidence of active-sandbox adoption after worker death or distributed exactly-once ownership.

The README's `--n-concurrent 100 --env daytona` command establishes configuration support, not a measured100/1000 reliability result. No benchmark or tests executed in this review. Syn must still own durable placement, per-pool quotas/admission, token/provider rate limits, backoff/jitter, leases/fencing, crash reconciliation, orphan reaping, cost ledger, budget kill, persistent capture and tenant authorization. Harbor is not a replacement for the existing event-sourced orchestration lane.

## Gotchas worth avoiding

1. `stream=True` means SSH exec/TCP forwarding, not general streamed logs (`capabilities.py:13-14`). E2B and OpenSandbox Harbor adapters don't wire the output callback although their SDKs can stream. Model capabilities separately: log streaming, PTY, SSH, TCP forwarding.
2. `stop(delete=False)` differs radically across backends. Define retained/stopped/deleted states and billing explicitly. E2B still kills (`e2b.py:281-297`); OpenSandbox leaves it alive (`opensandbox.py:555-567`); Docker can down or stop depending flags (`docker/docker.py:1183-1226`).
3. OpenSandbox user override silently falls back if SDK lacks uid or username is neither numeric nor root (`opensandbox.py:340-373`). This is inappropriate for a security requirement. Syn/APSS should reject unfulfillable required identity, reserve fallback for advisory preference.
4. Docker merges stderr into stdout (`docker/docker.py:729-737`) whereas E2B/OpenSandbox keep channels. Declare capture fidelity, rather than claiming every backend has equivalent stdout/stderr.
5. Transfers/results remain buffered. E2B upload_dir reads every file into a list then batches20 (`e2b.py:324-351`); OpenSandbox upload_dir reads all bytes and writes all entries (`opensandbox.py:592-621`); both download_file buffer one file; Docker streamed output still accumulates lines (`docker/docker.py:838-885`). Streaming UI does not imply bounded-memory runtime. Syn needs chunking/backpressure, quota, object storage references.
6. Build-cache identity appears incomplete for some cases. E2B alias derived from environment content only, but CPU/RAM embedded in template build and reuse skips build; changing resource settings with same env risks reuse of wrong template. Also `environment_content_hash` includes prebuilt image string only when no candidate files exist; changing image with loose files may preserve hash. Inference from `e2b.py:103-108,180-214,254-260`, `definition.py:88-140`; not live reproduced. Include all execution-affecting inputs and immutable digests in cache key.
7. OpenSandbox adapter advertises gpus=True based on expressibility in API, not deployed backend availability (`opensandbox.py:142-157`); deployment-level capabilities need discovery/verification too. Storage omitted rather than enforceable (`opensandbox.py:266-287`).
8. Best-effort cleanup loses local handle even after stop error (`e2b.py:289-295`, `opensandbox.py:555-567`); async shield cannot survive process death. Durable deletion request and orphan reconciliation remain necessary.

## Commands (examples, not executed)

| Task | Command | Notes |
|---|---|---|
| Install pinned SDK extras | `uv tool install 'harbor[e2b,opensandbox]==0.24.0'` | Optional vendor deps; pyproject.toml:52-69. |
| Inspect CLI | `harbor run --help` | CLI aliases hr/hb exist, pyproject.toml:36-39. |
| Inspect provider options | `harbor run --help` | Review environment and concurrency flags before a paid run. |
| Inspect single-trial options | `harbor trial start --help` | No agent started during research. |
| OpenSandbox config | `harbor run -c config.yaml` | Config environment.type=opensandbox and kwargs domain/api_key/protocol. |
| Resume evaluation | `harbor job resume --job-path /path/to/job` | Local completed-trial reconciliation; singular group canonical, plural hidden alias in cli/main.py:138,151. |

## Config and env

| Option | Default / semantics | Source |
|---|---|---|
| n_concurrent_trials |4, integer>=1; per-agent caps optional | models/job/config.py:415-423 |
| retry.max_retries |0 | models/job/config.py:291-321 |
| environment.delete |true | models/trial/config.py:196-205 |
| environment.stream |false, SSH/TCP profile | same |
| cpu/memory enforcement |auto; limit/request/guarantee/ignore available | config.py:55-61,203-204 |
| OpenSandbox protocol |https | opensandbox.py:82 |
| request_timeout_sec |SDK default if unset (comment30s); override for cold pulls | opensandbox.py:238-243 |
| readiness/server expiry |86400sec each, poll2sec | opensandbox.py:84-88 |
| E2B server expiry |86400sec | e2b.py:231 |

| Variable | Purpose |
|---|---|
| E2B_API_KEY |Required credential checked before jobs queued, e2b.py:69-80. |
| OPENSANDBOX_DOMAIN |Fallback server address; may supply constructor domain instead, opensandbox.py:100-103. |
| OPENSANDBOX_API_KEY |Optional; explicit empty kwarg honored, opensandbox.py:104-106. |
| OPENSANDBOX_LIVE_PROTOCOL / SERVER_PROXY / IMAGE |Live test options only, not production adapter config; tests/integration/environments/test_opensandbox_live.py:1-45. |

## Primary source links

- [Base contract and identity](https://github.com/harbor-framework/harbor/blob/b53b8134e1241686dca7759af188f987ecc48e8b/src/harbor/environments/base.py#L110)
- [Capabilities](https://github.com/harbor-framework/harbor/blob/b53b8134e1241686dca7759af188f987ecc48e8b/src/harbor/environments/capabilities.py#L12)
- [E2B safe dispatch](https://github.com/harbor-framework/harbor/blob/b53b8134e1241686dca7759af188f987ecc48e8b/src/harbor/environments/e2b.py#L432)
- [OpenSandbox readiness/cleanup](https://github.com/harbor-framework/harbor/blob/b53b8134e1241686dca7759af188f987ecc48e8b/src/harbor/environments/opensandbox.py#L376)
- [Local concurrency and retries](https://github.com/harbor-framework/harbor/blob/b53b8134e1241686dca7759af188f987ecc48e8b/src/harbor/trial/queue.py#L20)
- [Resource policy modes](https://github.com/harbor-framework/harbor/blob/b53b8134e1241686dca7759af188f987ecc48e8b/src/harbor/models/trial/config.py#L55)
- [Content cache key](https://github.com/harbor-framework/harbor/blob/b53b8134e1241686dca7759af188f987ecc48e8b/src/harbor/environments/definition.py#L82)
- [Mock E2B regression tests](https://github.com/harbor-framework/harbor/blob/b53b8134e1241686dca7759af188f987ecc48e8b/tests/unit/environments/test_e2b.py#L236)
- [Mock OpenSandbox regression tests](https://github.com/harbor-framework/harbor/blob/b53b8134e1241686dca7759af188f987ecc48e8b/tests/unit/environments/test_opensandbox.py#L676)
- [OpenSandbox Harbor adapter PR2054](https://github.com/harbor-framework/harbor/pull/2054) found via official release notes; not independently reviewed.

External official docs searched and found stale install guidance saying OpenSandbox backend only on main. Pinned release code proves present in v0.24.0. Prefer stable source over that page: https://open-sandbox.ai/examples/harbor-evaluation.
