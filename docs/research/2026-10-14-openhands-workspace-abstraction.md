# OpenHands workspace and runtime abstractions: what APSS and agentic-workspace should learn

Date: 2026-10-14. Author: research agent (Opus 5.5). Status: research note, not an ADR.

Method: static reading of shallow clones at pinned commits under
`/private/tmp/openhands-research-20261013/src/`. Nothing from these repos was executed or
installed. Claims marked **(inferred)** come from reading code paths, not from running them.
Claims marked **(unverified)** could not be checked against a primary source.

## TL;DR

- **The repo layout has moved.** `OpenHands/OpenHands` is now "Agent Canvas", a TypeScript
  frontend. The V0 runtime layer (`action_execution_server`, the E2B/Modal/Runloop/Daytona
  runtimes) is gone from every public repo we cloned. `OpenHands/legacy` at HEAD contains
  only `analytics, app_server, db, server`.
- **The live abstraction has three layers.**
  - **Workspace:** `BaseWorkspace`, a thin synchronous ABC in `software-agent-sdk`.
  - **In-sandbox server:** `agent-server`, a FastAPI service that runs the agent loop, bash,
    files and git inside the sandbox.
  - **Sandbox control plane:** `SandboxService`, with Docker, Process, Kubernetes
    (agent-sandbox CRDs) and Remote backends. Remote calls the **closed-source** `runtime-api`
    image that runs OpenHands Cloud.
- **The unit is a conversation (sandbox per conversation), not an operation.** There is no
  idempotency key, no operation ref, no typed status/error split, no gap reporting and no
  finalization receipt. APSS 0.2.0 is materially stronger as a contract.
- **Their best ideas are in the code, not the interfaces.** Worth adopting:
  - stop-before-spawn recording;
  - single-flight start, with a delete that waits for an in-flight start;
  - owner-labelled containers plus a startup sweep;
  - Docker-assigned loopback port readback;
  - a seq-cursor session socket that drops the connection, never a frame;
  - generation-fenced owner leases;
  - honest restart recovery (RUNNING becomes ERROR, with an explicit event);
  - secrets passed with `-e NAME`, value off argv;
  - a client-chosen `session_id` that makes remote start reattachable.
- **They are exposed to most of our 8 bug classes.** Process-group-only kill, with a likely
  `getpgid`-after-reap hole. `stop` returns success without confirmation. Transient errors
  are reported as MISSING. Start tasks are fire-and-forget, so start rows can stick. Docker
  clients inherit host env. Secrets enter the sandbox in plaintext env.
- **Scale evidence is planning guidance, not measurement.** Their enterprise sizing guide
  gives a 1,000-peak-sandbox table (5 to 96 nodes of 16 vCPU / 64 GiB). The talk says
  Kubernetes "supports thousands". Neither shows a measured fleet result.
- **Recommendation: borrow patterns, not dependencies.** Neither layer belongs inside our
  contract. A thin APSS provider over an OpenHands remote runtime is possible (see Q5), but
  it would be a degraded-capability provider, and `runtime-api` is closed.

## Evidence table (pinned)

| Repo | Commit | Committed | What it holds | Notes |
|---|---|---|---|---|
| [OpenHands/software-agent-sdk](https://github.com/OpenHands/software-agent-sdk/tree/6e7a8532ef4426da08b5c06dd57cf4795303be01) | `6e7a8532ef4426da08b5c06dd57cf4795303be01` | 2026-10-14 | `openhands-sdk` (BaseWorkspace, Local/Remote), `openhands-workspace` (Docker, APIRemote, Cloud, AgentSandbox, Apptainer), `openhands-agent-server`, `openhands-tools` | Primary source |
| [OpenHands/legacy](https://github.com/OpenHands/legacy/tree/ee9e78b7defdfa744e0bbe48c9cafa90b6135ad7) | `ee9e78b7defdfa744e0bbe48c9cafa90b6135ad7` | 2026-07-25 | V1 `app_server` sandbox services (Docker, Remote, Process) | V0 `openhands/runtime/` absent; agent-server consumed as pip `openhands-agent-server==1.37.1` (`pyproject.toml:61-62`) |
| [OpenHands/sandbox-server](https://github.com/OpenHands/sandbox-server/tree/4abe6a41cdbd55f18327bd8d5244a918c95ac692) | `4abe6a41cdbd55f18327bd8d5244a918c95ac692` | 2026-09-28 | Extracted control plane; adds the Kubernetes (agent-sandbox) backend | Supersedes legacy app_server |
| [OpenHands/OpenHands-Cloud](https://github.com/OpenHands/OpenHands-Cloud/tree/1a2edb87b8bc0b758173a0cbfe336378db3550d0) | `1a2edb87b8bc0b758173a0cbfe336378db3550d0` | 2026-10-13 | Helm, terraform, Replicated config | `runtime-api` is a closed image `ghcr.io/openhands/runtime-api:0.11.1` (`charts/openhands/charts/runtime-api/values.yaml:2-5`) |
| [OpenHands/docs](https://github.com/OpenHands/docs/tree/d27d7a0d86bcfd65b184629e1577e8bb9270b4d2) | `d27d7a0d86bcfd65b184629e1577e8bb9270b4d2` | 2026-10-14 | SDK and enterprise docs, sizing | |
| [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands/tree/bf483c12efbfae5c0ab586293d8bbc92f712bbed) (Agent Canvas) | `bf483c12efbfae5c0ab586293d8bbc92f712bbed` | 2026-10-14 | Frontend; backend registry | Not a sandbox (`docs/architecture.md:14-19`) |
| Talk | n/a | 2026-07-01 | Robert Brennan, "Sandboxes Aren't Optional: 4 Ways to Isolate Coding Agents", AIE World's Fair 2026, https://www.youtube.com/watch?v=iH_wV8BbS24 | **Transcript not obtained** (YouTube 429). Content comes from the official abstract plus third-party summaries |
| Paper | arXiv 2511.03690 v1 | 2025-11-05 | "The OpenHands Software Agent SDK" | Read from HTML v1 |

Path prefixes used below:

| Prefix | Path |
|---|---|
| `S/` | `software-agent-sdk/openhands-sdk/openhands/sdk/` |
| `W/` | `software-agent-sdk/openhands-workspace/openhands/workspace/` |
| `A/` | `software-agent-sdk/openhands-agent-server/openhands/agent_server/` |
| `T/` | `software-agent-sdk/openhands-tools/openhands/tools/` |
| `SS:sb/` | `sandbox-server/openhands/app_server/sandbox/` |
| `SS:ac/` | `sandbox-server/openhands/app_server/app_conversation/` |
| `OC:` | `OpenHands-Cloud/` |
| `D:` | `docs/` |

Line numbers in `legacy` and `sandbox-server` differ by a few lines for the same code. The
`SS:` citations are from sandbox-server.

## 1. Abstractions

### 1.1 Workspace (SDK)

| Class | Location | Mechanism |
|---|---|---|
| `BaseWorkspace` | `S/workspace/base.py:28` | Pydantic ABC, **sync** |
| `LocalWorkspace` | `S/workspace/local.py:17` | host subprocess |
| `RemoteWorkspace` | `S/workspace/remote/base.py:51` | HTTP to agent-server |
| `AsyncRemoteWorkspace` | `S/workspace/remote/async_remote_workspace.py:15` | same, async |
| `DockerWorkspace` | `W/docker/workspace.py:53` | `docker` CLI, one container |
| `DockerDevWorkspace` | `W/docker/dev_workspace.py:10` | builds the image first |
| `APIRemoteWorkspace` | `W/remote_api/workspace.py:19` | runtime-api `/start`, `/sessions/{id}` |
| `OpenHandsCloudWorkspace` | `W/cloud/workspace.py:53` | Cloud `/api/v1/sandboxes` |
| `AgentSandboxWorkspace` | `W/agent_sandbox/workspace.py:46` | kubernetes-sigs/agent-sandbox SandboxClaim from a SandboxWarmPool, `kubectl port-forward` |
| `ApptainerWorkspace` | `W/apptainer/workspace.py:28` | apptainer instance |
| `Workspace(...)` factory | `S/workspace/workspace.py:12,36-49` | `host` set means Remote, otherwise Local |

**Not found in current source:** E2B, Modal, Runloop and Daytona classes. Only V0 doc pages
remain, at `D:openhands/usage/v0/runtimes/V0_{e2b,runloop,daytona,modal}.mdx`.

**Contract.**
- Required methods (`S/workspace/base.py:171-282`):
  - `execute_command(command, cwd=None, timeout=30.0) -> CommandResult`
  - `file_upload` / `file_download -> FileOperationResult`
  - `git_changes`, `git_diff`
- Optional methods: `pause()` / `resume()`, which raise NotImplementedError by default.
- `__exit__` does nothing in the base class.
- `CommandResult` is `{command, exit_code, stdout, stderr, timeout_occurred}`
  (`S/workspace/models.py:20-29`).

There is no workspace ref, no operation id, no status type and no error taxonomy.

**Remote operations** are factored as "sans-IO" generators that yield request kwargs. They
are driven by a sync `httpx.Client` or an async one (`S/workspace/remote/base.py:109-116`,
`async_remote_workspace.py:53-75`). It is a neat way to keep sync and async parity.

**Remote command model** (`S/workspace/remote/remote_workspace_mixin.py`):
- `POST {prefix}/bash/start_bash_command` returns an id (`:82-102`).
- The client polls `GET {prefix}/bash/bash_events/search?command_id__eq&order__gt` every
  0.1 s until an `exit_code` appears (`:104-128, 210-249`).
- `POST .../bash_commands/{id}/stop`, where 404 counts as success (`:137-150`).
- `RemoteWorkspace` exposes the start, read and stop triple directly as `start_command`,
  `get_command_output` and `stop_command` (`S/workspace/remote/base.py:136-162`).

That triple is the closest thing they have to our start/status/cancel.

**Files, ports, browser:**
- Files are multipart upload and GET download (`mixin:286-403`).
- Ports are a fixed map from the control plane: `ExposedUrl` AGENT_SERVER, VSCODE,
  WORKER_1, WORKER_2 (`SS:sb/sandbox_models.py:27-30`).
- The browser is an `OH_ENABLE_BROWSER` flag (`A/docker_runtime/registry.py:427-429`).
- VNC is mentioned in the paper but not found in source (grep `vnc` returned 0 hits).

### 1.2 Agent-server (in sandbox)

- **Bash REST** (`A/bash_router.py`): `search` (`:36`), `start_bash_command` (`:100`), blocking
  `execute_bash_command` (`:112-124`), `stop` (`:136-155`).
- **Execution** (`A/bash_service.py`): `create_subprocess_shell(..., start_new_session=True,
  env=sanitized_env())` (`:293-301`).
- **Output storage:** each chunk is persisted as one JSON file per `BashOutput{order}` event.
- **Kill:** SIGTERM to the process group, then SIGKILL after 1 s (`:251-265, 380-399`).
- **Conversation events:**
  - Legacy socket `/sockets/events/{id}` with `resend_mode=all|since` on naive timestamps
    (`A/sockets.py:228-386`).
  - New `/sockets/session/{id}?after_seq=` (`A/session_socket.py:314-411`) sends a
    `SyncFrame{from_seq, through_seq}`, then the disk replay, then live events, deduped by seq.
- **Agent terminal tool:** tmux via libtmux, with a pty fallback
  (`T/terminal/terminal/factory.py:165-183`). A hard timeout returns a message telling the
  agent to send C-c; it **does not kill** (`T/terminal/terminal_session.py:389-415`).
- **Per-conversation Docker runtime inside agent-server** (`A/docker_runtime/registry.py`):
  - the agent-server can spawn one hardened container per conversation;
  - this is the best lifecycle code in the codebase (see section 7).

### 1.3 Sandbox control plane

- **Interface:** `SandboxService(ABC)` is **async** (`SS:sb/sandbox_service.py:112`). Methods:
  `search/get/start/resume/pause/delete`, `wait_for_sandbox_running`, `pause_old_sandboxes`.
- **Status:** `SandboxStatus = STARTING|RUNNING|PAUSED|ERROR|MISSING`
  (`SS:sb/sandbox_models.py:9-15`). It has no file or command operations; those go to the
  agent-server.
- **Backends** are selected by `RUNTIME` (`SS:openhands/app_server/config.py:338-360`):

  | Backend | Location | Notes |
  |---|---|---|
  | Docker | `docker_sandbox_service.py` | docker SDK `from_env()` singleton, `init=True` (tini) |
  | Kubernetes | `kubernetes_sandbox_service.py` | `SandboxClaim` + `warmPoolRef`; pause by patching `spec.operatingMode: Suspended` |
  | Process | `process_sandbox_service.py` | |
  | Remote | `remote_sandbox_service.py` | runtime-api: `POST /start`, `GET /sessions/{id}`, `/sessions/batch`, `/list`, `POST /pause|/resume|/stop {runtime_id}` |

### 1.4 Sync or async?

- The workspace contract is sync, with an async twin for remote only.
- The control plane is async.
- The agent-server is async FastAPI.
- The SDK's `execute_command` blocks the caller. Long work goes through conversations, not
  through the workspace contract.

## 2. Execution transport

| Concern | What the source shows |
|---|---|
| Send | REST `start_bash_command` returns a command id. Server default timeout 300 s (`A/models.py:626-629`); client default 30 s |
| Observe | **Polling** `bash_events/search` with an `order__gt` cursor. Output is published only when the buffer exceeds **1 MiB** (`A/bash_service.py:25`) or at exit (`:327-347, 400-416`). Below 1 MiB nothing is streamed live **(inferred from code)** |
| Reconnect / replay | The session socket replays from disk with `after_seq` (`A/session_socket.py:294-335`). It subscribes first and then reads the mark, so there is no lost window (`:365-415`). Overflow "drops the connection, never a frame" (`:62-73`). The SDK's own `RemoteConversation` still uses the **legacy socket with no cursor** and reconciles by a full REST scan, swallowing fetch errors (`S/conversation/impl/remote_conversation.py:237, 369-419, 400-402`) |
| Timeouts | Server: `asyncio.wait_for(gather(read, read, wait), timeout)` (`A/bash_service.py:357-370`). Client timeout synthesises exit -1 and **does not call stop** (`mixin:251-259`) |
| Cancel | `stop_bash_command` sends SIGTERM to the pgroup, waits 1 s, sends SIGKILL, waits 1 s, then **returns True regardless** (`A/bash_service.py:439-468`). A stop before spawn is recorded in `_stop_requests` and applied right after spawn (`:280-281, 302-307, 455-458`) |
| Process-tree kill | Process group only; no cgroup and no psutil (grep 0). The group is found with `os.getpgid(process.pid)` (`:257`); `ProcessLookupError` is swallowed (`:258-259`) |
| Errors | Any client exception becomes `CommandResult(exit_code=-1, stderr="Remote execution error")` (`mixin:273-284`). Unavailable, failed and timed-out are indistinguishable by type |
| Retention | `bash_events_retention_seconds` deletes event files (`A/bash_service.py:470-538`, `A/api.py:314-336`). A late poller sees fewer events with **no gap marker** **(inferred)** |

## 3. Lifecycle and recovery

**Pause and resume.**
- Docker uses `docker pause` / `unpause`.
- Kubernetes uses `operatingMode` Suspended or Running, which drops the pod and keeps the PVC
  (`SS:sb/kubernetes_sandbox_service.py:531-551`).
- On remote, pause clears the session key and resume rotates it
  (`SS:sb/remote_sandbox_service.py:521-575`).
- The agent-server closes event services before a sandbox pause
  (`A/conversation_service.py:683-715`).

**Reattach.**
- `APIRemoteWorkspace` reattaches by `session_id` via `GET /sessions/{id}`, and resumes the
  session if it is paused (`W/remote_api/workspace.py:157-182, 235-243`).
- `DockerWorkspace` never reattaches (`W/docker/workspace.py:151-156`).
- On restart, the server-side Docker backend treats the container list (name prefix) as its
  registry (`SS:sb/docker_sandbox_service.py:295-306`).

**Idle handling and warm pools.**
- Agent-server: `conversation_idle_ttl_seconds` eviction, skipped while a run or subscriber
  is active (`A/conversation_service.py:2083-2147`, `A/docker_runtime/registry.py:340-400`).
- Cloud reaper: idle 1200 s, dead after 60 days, CronJobs every 5 min
  (`OC:charts/openhands/charts/runtime-api/values.yaml:207-241`).
- Docs: idle sessions pause, then are deleted; there is a hard **12 h max session**,
  force-paused, not configurable (`D:enterprise/conversations-and-sandboxes.mdx:316-336`).
- Warm pools exist but are **effectively off**:
  - Cloud warm-runtimes CronJob `count: 0` (`OC:.../runtime-api/values.yaml:283-326`), and a
    claim needs an exact env match (`templates/warm-runtimes-configmap.yaml:22-57`);
  - Kubernetes: "pre-warmed replicas are never used today", because any claim with
    `spec.env` cold-starts and the session key is passed as env
    (`SS:deploy/kubernetes/README.md:61-73`).

**Crash handling.**
- After an agent-server restart, RUNNING conversations become ERROR, with an `AgentErrorEvent`
  "A restart occurred while this tool was in progress" for the unmatched action
  (`A/event_service.py:1328-1370`). There is no reattach of an in-flight tool.
- A split-brain guard uses a file lease `owner_lease.json`: 45 s TTL, generation fencing,
  `guarded_write`, takeover only on expiry or a dead owner pid
  (`A/conversation_lease.py:18-20, 122-232`).
- The control-plane start task is an unreferenced `asyncio.create_task`
  (`SS:ac/app_conversation_router.py:406`), catching `Exception` only. A crash leaves start
  rows in WORKING. The backstop is a daily cleaner CronJob at 03:00
  (`OC:charts/openhands/values.yaml:361-367`).

## 4. Security

**Session API key.**
- Sent as `X-Session-API-Key`, checked with list membership (not constant-time). Auth is
  **disabled when no keys are configured** (`A/dependencies.py:19, 36`).
- Plaintext in the container env on Docker (`SS:sb/docker_sandbox_service.py:442-446`).
- Plaintext in the Kubernetes `SandboxClaim.spec.env` (`SS:sb/kubernetes_sandbox_service.py:402-416`).
- Hash-only storage on remote (`SS:sb/remote_sandbox_service.py:76-78, 503-508`).
- Placed in the VSCode URL query string (`SS:sb/docker_sandbox_service.py:181, 212`).

**Secrets do enter the sandbox.**
- SDK `update_secrets` POSTs plaintext values, or `LookupSecret`s with `expose_secrets=True`,
  to the in-sandbox server (`S/conversation/impl/remote_conversation.py:1617-1640`).
- The terminal exports only the secrets whose names appear in the command
  (`S/conversation/secret_registry.py:219-248`).
- Output is masked as `<secret-hidden>` with a chunk-boundary-aware masker (`:120-155`).
- Docs: secrets are "automatically exported as environment variables in the agent's runtime
  environment" (`D:openhands/usage/settings/secrets-settings.mdx:8-10`).
- The sandbox can pull any user secret by name with its session key
  (`SS:sb/sandbox_router.py:127-220`).
- `LookupSecret` with a JWT `X-Access-Token` exists when `web_url` is set, and is a raw
  `StaticSecret` otherwise (`SS:ac/live_status_app_conversation_service.py:1184-1211`).

**Host env leaks in.**
- `LLM_*`, `LMNR_*` and `OH_AGENT_SERVER_ENV` are forwarded (`SS:sb/sandbox_spec_service.py:151-208`).
- The process backend copies all of `os.environ` (`SS:sb/process_sandbox_service.py:125`).
- On Cloud, LLM and AWS credentials go into `global.agentServerEnv`, rendered into a
  **ConfigMap** for warm runtimes (`OC:replicated/openhands.yaml:937-1082`,
  `templates/warm-runtimes-configmap.yaml:32-57`).

**Isolation.**
- Cloud default is `sysbox-runc` (`OC:.../runtime-api/values.yaml:66`), installed by a
  privileged DaemonSet (`OC:charts/infra/templates/sysbox-installer.yaml`).
- gVisor and Kata are not found in the Cloud charts.
- The control plane's default `runtime_class='gvisor'` is **silently dropped**; only sysbox
  is forwarded (`SS:sb/remote_sandbox_service.py:491-493`).
- The Kubernetes template has `# runtimeClassName: gvisor` commented out
  (`SS:deploy/kubernetes/sandboxtemplate.yaml:58`).

**Network.**
- No NetworkPolicy for sandboxes; the runtime-api ClusterRole lacks the verb
  (`OC:.../runtime-api/templates/clusterrole.yaml:9-37`).
- Docs push egress control to the VPC firewall (`D:enterprise/docker-in-sandbox.mdx:70-80`).

**Multi-tenancy.**
- Per-user `OH_SANDBOX_MAX_NUM_SANDBOXES=10`, "not a cluster-wide cap"
  (`OC:charts/openhands/values.yaml:121-126`).
- Conversations grouped into one sandbox share its filesystem, credentials and failure
  domain (`D:enterprise/conversations-and-sandboxes.mdx:41-43`).

**Hardening done well.** The agent-server per-conversation runtime runs:
- `--user uid:gid`, `--cap-drop ALL`, `no-new-privileges`, `core=0`;
- optional memory, cpus and pids limits;
- an owner label;
- `-p 127.0.0.1::8000` with readback;
- secrets as `-e NAME` with the value in the child process env, not argv
  (`A/docker_runtime/registry.py:413-503`).

`DockerWorkspace` puts `-e KEY=VALUE` on argv instead (`W/docker/workspace.py:210-212`).

## 5. Scale

- **Docs sizing** (`D:enterprise/sizing-guide.mdx:40-80`):
  - single VM: 5 to 100 peak sandboxes, with 100 needing 96 vCPU / 384 GiB;
  - Helm: **1,000 peak sandboxes on 5 to 96 sandbox nodes of 16 vCPU / 64 GiB**, Postgres on
    a dedicated node from 500;
  - planning unit about 0.5 vCPU / 4 GiB / 10 GiB per sandbox.

  This is planning guidance. No measurement is attached **(unverified as measured)**.
- **Per-sandbox Cloud request:** 3072 Mi memory and 500 m CPU, 10 Gi ephemeral
  (`OC:charts/openhands/values.yaml:1110-1114`).
- **runtime-api:** HPA of 3 to 6 replicas (`OC:.../runtime-api/values.yaml:201-205`). No
  cluster-wide ResourceQuota (grep 0). The global cap is node capacity.
- **Concurrency caps:** enforced by **pausing the oldest RUNNING sandboxes** before a
  start, never by rejecting (`SS:sb/sandbox_service.py:318-359`). It is check-then-act, so
  concurrent starts can overshoot.
- **Hosted runtime API:** `runtime.all-hands.dev` is "designed primarily for benchmark
  evaluation at scale, not for building production applications"
  (`D:sdk/guides/agent-server/api-sandbox.mdx:9, 12`).
- **Costs:** none stated for runtime. The paper only cites LLM test and benchmark costs.

## 6. The talk: claims vs source

The talk is Robert Brennan, "Sandboxes Aren't Optional: 4 Ways to Isolate Coding Agents",
AIE World's Fair 2026, 2026-07-01, https://www.youtube.com/watch?v=iH_wV8BbS24.
**Transcript not obtained.** The claims below come from the official abstract (quoted) or
from the BigGo and daily.dev summaries (secondary). An earlier talk, "Software Development
Agents: What Works and What Doesn't" (AIE 2025), touches the topic only lightly.

| Claim | Source of claim | What the source code shows |
|---|---|---|
| Four isolation options: local Docker, Claude Code + GitHub Actions, long-lived VM/Mac mini, Kubernetes pod per session | Summary | Consistent: Docker, Process and Kubernetes backends exist; the per-conversation container exists. GitHub Actions is not an OpenHands backend |
| Kubernetes "supports thousands" | Summary quote | Docs table goes to 1,000 peak. No measurement found. The Kubernetes warm pool is disabled in practice |
| Pod per session, thrown away | Summary | Partly. Sandboxes are per conversation, but **pause keeps a PVC** and resumes. Idle leads to pause, then deletion. Not ephemeral by default |
| Least privilege ("agents and humans should only have access to the things they need") | Summary quote | Contradicted in places: secrets in plaintext env, host `LLM_*` forwarding, the sandbox can fetch any user secret by name, no NetworkPolicy |
| Egress controls, RBAC, audit trail, 50 parallel agents demo, reference k8s config | **Abstract only** | Not verified in the talk. No sandbox NetworkPolicy in the charts. The RBAC is for runtime-api, not tenants |
| "Sandboxing is not a panacea", escapes exist | Summary quote | Consistent with sysbox (not a VM) as the Cloud default |
| Agent Canvas "runs any sandbox type and any harness" | Summary paraphrase | True as architecture: Canvas plus agent-server plus ACP agents (Claude Code, Codex). Canvas itself is not a sandbox (`OpenHands:docs/architecture.md:14-19`) |
| Paper: "Sandboxing should be opt-in, not universal"; V0 sandboxed every tool call and the V1 redesign fixes the state drift | Paper quote | Matches the code: `LocalWorkspace` is the default, and the agent loop runs *inside* agent-server next to its tools |

The architectural message is **move the agent loop into the sandbox and talk to it over
HTTP and WebSocket**. Syntropic137 already does this: the harness runs inside the workspace.
The new part for us is that they made the in-sandbox server the stable API, rather than
`docker exec`.

## 7. Our 8 lifecycle bug classes

**Legend:**

| Mark | Meaning |
|---|---|
| H | handled |
| P | partly handled |
| X | exposed |
| n/a | not applicable |

| # | Bug class | OpenHands | Evidence | Take for us |
|---|---|---|---|---|
| a | Double-forked orphans survive cancel | **X** in-sandbox; H only at container granularity | Process-group kill only (`A/bash_service.py:251-265, 300`); a grandchild that calls setsid escapes. **(inferred, high confidence)** If the leader was already reaped by `process.wait()` while a background child holds the pipes, `os.getpgid(pid)` raises `ProcessLookupError`, which is swallowed (`:257-259`), so **nothing is killed**. `os.killpg(pid, sig)` with the pid saved at spawn would work. The process backend has no session and kills one pid (`SS:sb/process_sandbox_service.py:146-148, 394-405`). Docker and Kubernetes delete tear down the PID namespace; tini reaps zombies (`SS:sb/docker_sandbox_service.py:524-526`) | Never derive the pgid after a wait. Store pgid = pid at spawn. Escalate to a cgroup or PID-namespace kill (container stop) when descendants remain; APSS 0.2.0 already says "escalate". Add a fixture: leader exits, setsid grandchild sleeps, cancel must reach `cancelled` only after the grandchild is gone |
| b | Interrupted cancel publishes unconfirmed | **X** | `stop_bash_command` returns True after a failed SIGKILL wait (`A/bash_service.py:459-468`), and the router says Success (`A/bash_router.py:151-152`). A stop recorded before spawn is acknowledged before any kill (`:456-458`). The server publishes interrupt state after a 5 s shielded wait even if the task lives (`A/event_service.py:1984-1993`). Process delete returns True on `OSError` (`SS:sb/process_sandbox_service.py:418-423`). Remote pause returns True on 2xx without confirmation. **Good counterexample:** remote delete raises `SandboxDeleteRetryError` (503) and keeps the row on transient failure (`SS:sb/remote_sandbox_service.py:604-657`) | Keep APSS "cancelled only after confirmed". Distinguish *cancel accepted* from *cancelled*. Adopt the 503-retain-row pattern for destroy |
| c | Cancel before launch ack deadlocks | **H** at the bash layer; **P** elsewhere | Placeholder `_processes[id]=None` registered synchronously, stop recorded in `_stop_requests`, applied immediately after spawn (`A/bash_service.py:280-281, 302-307`). Registry `stop()` awaits the in-flight start, then stops it (`A/docker_runtime/registry.py:313-327`). But `docker run` via `subprocess.run` has **no timeout** (`:491`), so a hung daemon blocks both **(inferred)**. Control plane: delete before the DB commit returns 404 and the runtime launches anyway (`SS:sb/remote_sandbox_service.py:466-519, 618-620`); this is a *lost* cancel rather than a deadlock | Adopt the placeholder-plus-pending-stop pattern for our launch header: a cancel arriving before the header is recorded and applied when the header appears, and never blocks on the FIFO. Bound every daemon call with a deadline |
| d | Destroy racing a start | **H** in the agent-server registry; **X** in the control plane and SDK | Registry: one `asyncio.Lock`, a `_starts` single-flight task map, a `_deleting` set checked before and after start, the superseded start's container stopped, and stop-on-`BaseException` in `_build_container` (`A/docker_runtime/registry.py:253-327, 509-512`). Control plane: no locks (`SS:sb/docker_sandbox_service.py` start and delete), and the finalizer count-then-delete races grouped reuse (`SS:ac/app_conversation_router.py:887-919`). SDK `APIRemoteWorkspace` sets `_runtime_id` only after the response, so a `/start` timeout orphans the runtime (`W/remote_api/workspace.py:233, 391-392`) | Copy the registry pattern. Plus: persist the intended resource id *before* `/start`, as `session_id` does for remote, so a lost response can be reconciled |
| e | Permanently stuck intermediate states | **P** | Bounded readiness that also checks `docker inspect Running` and fails fast (`A/docker_runtime/registry.py:514-536`; `W/docker/workspace.py:316-351`). Restart turns RUNNING into ERROR (`A/event_service.py:1328-1370`). Exposed: Kubernetes STARTING is indefinite unless the optional TTL is set (`SS:sb/kubernetes_sandbox_service.py:276-295, 506-511`). Fire-and-forget start tasks leave WORKING rows, cleaned by a **daily** CronJob (`OC:charts/openhands/values.yaml:361-367`). Docker `exited` maps to PAUSED, so waiters poll to timeout (`SS:sb/docker_sandbox_service.py:147-159`). The chart admits runtimes "stuck in `starting`" (`OC:.../runtime-api/values.yaml:41-46`) and adds `RUNTIME_PENDING_REAP_ENABLED` | Every non-terminal state needs an owner and a deadline. Reconcile at startup, not daily. Never map "exited" to a resumable state without an exit record |
| f | Silent observation gaps | **P** | Good: session socket `after_seq`, subscribe-before-mark, dedupe, and "drop connection, never a frame" (`A/session_socket.py:62-73, 365-415`). Exposed: unreadable events skipped with only a log (`:277-291`), so a gap is visible only as a seq hole. Bash retention deletes without a gap marker (`A/bash_service.py:470-538`). The SDK's own client uses the cursorless legacy socket and swallows reconcile errors (`S/conversation/impl/remote_conversation.py:237, 400-402`). **(inferred)** `order__gt` is applied *after* page slicing and the client ignores `next_page_id` (`A/bash_service.py:232-247`, `mixin:111-128`), so more than 100 events can stall the poll. Transient runtime-api errors become MISSING (`SS:sb/remote_sandbox_service.py:363-371, 840-851`), and Docker `APIError` returns an empty list (`SS:sb/docker_sandbox_service.py:357-358`) | Validates APSS's explicit `gap` and `provider_unavailable` vs `lost`. Add the disconnect-as-backpressure rule to the observation spec |
| g | Blocking FIFO opens | **n/a** (no FIFOs) | They avoid FIFOs entirely: pipes from asyncio subprocesses and log files "to avoid pipe-buffer deadlocks" (`SS:sb/process_sandbox_service.py:143-148`). **(inferred)** One exposure: `open(path, "rb")` before an `S_ISREG` check in the archive helper (`A/file_router.py:591-599`) | Supports our direction: open FIFOs with `O_NONBLOCK`, or replace the FIFO launch header with a file plus marker line on stdout |
| h | Credential bindings steer the host Docker client env | **X** | Every `docker` CLI call inherits the full host env (`S/utils/command.py:52-53`; `W/docker/workspace.py:201, 253`; `A/docker_runtime/registry.py:491`). `docker.from_env()` is a global singleton in the control plane (`SS:sb/docker_sandbox_spec_service.py:28-32`). No `DOCKER_HOST` guard (grep 0). Mitigating detail: registry secrets are added under fixed `OH_*` names from an allowlist, so they cannot collide with `DOCKER_*` | Construct the Docker client from explicit provider config, never from the merged env. Keep credential-binding env in a separate dict used only for the workload. Fixture: a binding with target `DOCKER_HOST` must not change the daemon |

**Score:**

| Result | Classes |
|---|---|
| Handled well | c (bash layer), d (agent-server registry) |
| Partly handled | e, f |
| Exposed | a, b, h |
| Not applicable | g |

## 8. Comparison with APSS 0.2.0 and Harbor/OpenSandbox

| Dimension | APSS EXP-V1-0006 0.2.0 + AW 914129d | OpenHands (SDK + agent-server + SandboxService) | Harbor / OpenSandbox (prior note) |
|---|---|---|---|
| Unit | Operation in an opaque `WorkspaceRef` | Conversation in a sandbox; commands are secondary | Harbor: trial env; OpenSandbox: sandbox plus execd command |
| Start idempotency | `(workspace, operation_key)`, same spec gives the same ref | None for commands. Remote sandbox `session_id` is client-chosen, so it is *de facto* reattachable | None in Harbor; OpenSandbox none per command |
| Status | Typed `OperationStatus`; `lost` only when established; `provider_unavailable` is an error | `exit_code` in the last BashOutput, or -1. Sandbox: `MISSING` conflates unknown with gone | Varies by adapter |
| Observe | Bounded pages, opaque generation cursor, explicit `gap`, `complete` | Session socket `after_seq` (good) and bash polling with `order__gt` (weak); no gap signal | OpenSandbox SSE with no replay cursor; byte offsets in background logs |
| Cancel | Idempotent; `cancelled` only after the tree is confirmed gone, else escalate | pgroup SIGTERM then SIGKILL; returns success unconfirmed | Harbor: provider-dependent |
| Finalize | `TeardownReport` / `FinalizationOutcome`; retained plus a retry owner | None; delete is stop + remove + volume removal | None |
| Credentials | References only; `CredentialBinding` env or file; never persisted | Values in env and the session; masking in output; `LookupSecret` late binding | OpenSandbox endpoint headers carry authority |
| Capabilities | `ProviderDescriptor`; refuse unsupported | None; `runtime_class` silently dropped | Harbor capabilities model (good) |
| Warm pools | Out of APSS (syn scheduling) | agent-sandbox `SandboxWarmPool`; disabled in practice by per-claim env | OpenSandbox pool with ownership handoff (strongest) |
| Recovery | Reattach out (ADR-072); retained finalization record | Lease generations + RUNNING to ERROR; remote reattach by `session_id` | OpenSandbox reconnect by id; no command replay |
| Conformance | Behaviour fixtures (Python + Rust) | Large unit test suites; no cross-backend conformance suite found (not exhaustively searched) | Harbor per-env tests |

**Net.** OpenHands sits between Harbor (a broad provider zoo with uneven semantics) and
OpenSandbox (a stronger execution protocol and pool). Their distinctive contribution is the
in-sandbox **agent-server as the stable API**, plus a few well-engineered local lifecycle
primitives. None of the three provides APSS 0.2.0's operation-level guarantees.

## 9. Recommendations

### Adopt in APSS (spec or behaviour fixtures)

1. **Cancel-before-start fixture.** Cancel on a `pending` operation is recorded and applied
   once the process exists, and returns without blocking (OpenHands `_stop_requests`).
   Fixture: "cancel races start, process never runs the workload, or runs and is killed;
   state ends `cancelled`, exactly one terminal".
2. **Leader-exited-grandchild fixture** for class (a): "leader exits 0, setsid grandchild
   alive, cancel returns `cancelled` only after the grandchild is gone, else escalates". This
   is the exact hole in `A/bash_service.py:257`.
3. **Observation backpressure rule.** A provider MAY end an observation stream under
   backpressure, but MUST NOT drop a page within it. Resuming from the last cursor is
   lossless unless `gap` is reported. Mirror their `SyncFrame{from,through}` as an optional
   first page header.
4. **Unreadable record is a gap.** A corrupt or unreadable retained record MUST surface as
   `gap`, never as a silent skip (their `_read_page` logs and skips).
5. **Client-chosen resource identity** for providers without idempotent create. The
   orchestrator supplies a resource name or `session_id` before create, so a lost create
   response is reconciled by lookup. This makes the prior note's "persist identity before
   readiness" rule concrete.
6. **Refuse, do not drop, unsupported runtime classes.** Add a fixture for their
   `runtime_class='gvisor'` silent-drop bug; it is our `rejected_policy` /
   `unsupported_capability` rule.

### Adopt in agentic-workspace (implementation)

1. **Copy the `DockerConversationRegistry` lifecycle** (`A/docker_runtime/registry.py:253-327`):
   - one lock;
   - a `_starts` single-flight task map;
   - a `_deleting` set checked before and after start;
   - destroy awaits an in-flight start, then stops it;
   - stop the container on any `BaseException` during build.

   This closes (d) for the Docker provider.
2. **Owner label per provider instance**, swept at startup (`registry.py:242-251`), next to
   our existing orphan reaper. Label with the executor generation so a new generation does
   not reap a live sibling.
3. **Docker-assigned loopback ports with readback** (`-p 127.0.0.1::PORT`, then `docker port`,
   then assert loopback). No bind-test TOCTOU.
4. **Secrets via `-e NAME`**, with the value only in the child process env, never argv. Build
   that env from the credential-binding dict alone, never from `os.environ`. Build the Docker
   client from explicit provider config. Together these close (h).
5. **Readiness that fails fast:** poll health *and* container running state under a deadline.
   Every daemon subprocess call gets a timeout.
6. **Restart honesty:** on executor restart, unmatched in-flight operations become terminal
   `lost` only when established (container gone). Otherwise `provider_unavailable` until
   reconciled. Their RUNNING-to-ERROR event is the honest version of this.
7. **Evaluate kubernetes-sigs/agent-sandbox** (SandboxTemplate, SandboxWarmPool, SandboxClaim,
   `operatingMode: Suspended`, `runtimeClassName`) as the Kubernetes or Kata substrate behind
   a future provider. It may compete with or complement the self-hosted microVM pool plan.
   **Lesson from them:** warm pools only work if per-claim config is empty, so credentials
   must be injected *after* adoption. That is the same requirement as #1735 and our
   credential-reference model.
8. **Sans-IO generator pattern** for sharing request logic between sync and async Python
   clients, if the Python provider grows an async twin.

### Avoid

- A thin sync `execute_command(timeout=30) -> CommandResult` as the contract. It collapses
  unavailable, failed and timed-out into `exit_code=-1`.
- Client timeouts that do not cancel server work.
- Buffering output until 1 MiB or exit.
- `getpgid` after reap.
- `stop` returning success unconfirmed.
- Mapping transient control-plane errors to MISSING. That is our `lost` vs
  `provider_unavailable` rule exactly.
- Concurrency caps enforced by pausing the oldest sandbox with check-then-act. Admission
  belongs to syn's durable budget.
- Fire-and-forget start tasks reconciled daily, and detached deletes that return Success
  first.
- Secrets in plaintext env, ConfigMaps or CRD specs, or fetchable by name from inside the
  sandbox.
- Grouping several runs into one sandbox; it gives them a shared failure and credential
  domain.
- Relying on the closed `runtime-api` for any guarantee we cannot read.

### Provider behind our contract, or our contract behind their SDK?

**OpenHands as an APSS provider.** Feasible, but only as a **degraded-capability provider**,
and not now. The mapping would be:

| APSS operation | OpenHands call |
|---|---|
| `start` | `/start` with an orchestrator-chosen `session_id`, then agent-server `start_bash_command` |
| `status` | last `BashOutput` / `GET /sessions/{id}` |
| `observe` | session socket or bash search |
| `cancel` | `bash_commands/{id}/stop`, plus runtime `/stop` as escalation |
| `destroy` | `/stop` |

Gaps a shim must paper over:
- no operation idempotency key, so the shim keeps its own record per workspace;
- unconfirmed stop, so the shim escalates to runtime stop and reports that;
- no gap signal on bash retention;
- 1 MiB output buffering, which breaks live capture;
- `runtime-api` is closed, and the hosted API is "not for production".

Its `ProviderDescriptor` would have to declare `observation.integrity: continuity_detected`
at best. **Worth it only if a customer already runs OpenHands Cloud or Enterprise.**

**Our contract behind their `BaseWorkspace`.** Trivial to write
(`execute_command = start + observe until complete + status`), but it throws away everything
APSS guarantees. Useful only as a compatibility adapter that lets the OpenHands agent, or
an ACP harness driven by agent-server, run inside our workspaces. Low priority.

**Better target: their agent-server as a harness, not a provider.** It is an in-sandbox
server speaking ACP to Claude Code or Codex. That makes it a *harness* to install into an
APSS workspace via a recipe, like codex or claude today. It would then be subject to our
capture and finalization, not a substitute for them.

## 10. Open questions

1. **The talk's actual content.** Did it include the 50-parallel-agent demo, egress controls,
   RBAC, or the reference k8s config? We need the transcript; retry
   `uvx yt-dlp --skip-download --write-auto-subs --sub-langs en` on `iH_wV8BbS24`.
2. **`runtime-api` (closed).** What are its idempotency semantics for `/start` with an existing
   `session_id`? What does it do with the pending-reap logic, the warm-claim env match and
   cancel? These are unverifiable from source.
3. **Measured fleet numbers.** Do any exist for OpenHands Cloud (concurrent sandboxes,
   start latency, cost per sandbox-hour)? None found; only the sizing table.
4. **V0 runtime source** (action_execution_server, tmux PS1 protocol, E2B/Modal/Runloop/Daytona).
   It is absent from the cloned HEADs. Recover it from `All-Hands-AI/OpenHands` history before
   the split if the V0 patterns matter. Not done here.
5. **`getpgid`-after-reap hole** (`A/bash_service.py:257`). It is inferred from reading. It
   could be confirmed with a sandboxed reproduction on our side, which would also be a good
   APSS fixture seed. Possibly worth reporting upstream.
6. **agent-sandbox (kubernetes-sigs) for our 1,000 tier.** Does post-adoption credential
   injection exist upstream yet? OpenHands says no (`SS:deploy/kubernetes/README.md:61-73`).
   How does it compare to Kata-in-Docker on owned KVM for our microVM plan?
7. **Bash poll stall.** Does the `order__gt`-after-slice behaviour (`A/bash_service.py:232-247`)
   really stall clients past 100 events? It is inferred; it needs a test.
8. **Would adopting a seq-cursor socket** as an optional APSS observation transport conflict
   with the 0.2.0 page-and-cursor model? Hypothesis: no, if each frame carries the
   generation and offset cursor.
