# Plan: self-hosted microVM workspaces on owned KVM hardware (final, revised after cross-model review)

Target path once committed by an implement phase: `docs/plans/20261013_selfhosted-microvm-pool.md`.
This phase had Read/Grep/Glob/Write only (no git, no shell), so the doc is delivered here and is not committed.

## Sources and how each was read

| Tree | Revision | How this phase read it |
|---|---|---|
| syntropic137 working tree | `fd8ffd7a6` (main) | read in place; every unsuffixed citation below was re-opened in this phase |
| agentic-workspace submodule | as checked out under `lib/agentic-workspace/` (the reviewer records `5c4e5595`) | read in place |
| syntropic137 branch `docs/runtime-research-20261012` | `b4944839` | **not readable here** (no git). Citations suffixed `@b4944839` were read by the research or the reviewer through `git show`; they are carried, and each is marked |
| OpenSandbox | `531700ca` | **not on disk here**. Facts are from the reviewer's pinned-source reading (B1), which is consistent with the in-repo review's own wording |
| kata-containers | `7a3711be` | **not on disk here**. Facts are from the research's and reviewer's pinned reads |
| e2b-dev/infra | `fa7f9dbc` | from the research's shallow clone |
| nestybox/sysbox | `f7c43922` | from the research's shallow clone |

External citations are written `<repo>@<sha7>:<path>:<line>`. The brief's measured inputs (670 executions; 0.8-1.0 core and 0.6 GiB per active phase; idle stack 0.8 core / 6.7 GiB; implement-v3 p50 100 min) and the hardware prices are **not in the repo**. They are used here only as sizing hypotheses, and E0 re-measures them.

---

## TL;DR

**Leading candidate: Kata Containers with the Cloud Hypervisor (CLH) VMM, registered as a Docker runtime on each owned KVM box, driven by the existing `WorkspaceDockerProvider`, one ADR-072 executor per box.** This is option (C) in its Kata-in-Docker form, with sysbox (D) as the measured comparison arm.

It is a **candidate, not an established winner.** Nothing in source settles Docker-inside-a-Kata-guest, density, or credential reachability. A two-stage experiment (E0a/E0b) decides, and nothing past the configuration fix ships to production until it passes.

Three things this revision makes explicit that the first draft did not:

1. **Reusing the Docker provider does not make the pool APSS 0.2.0-compliant.** The pinned Python provider is still blocking `execute` and a `None` teardown. The pool ships behind the provider-operation-contract plan's Docker operation implementation, and then has to pass that contract's conformance suite *under the kata runtime*.
2. **Fixing the dropped `isolation_backend` setting must not break runc-only hosts.** Today's default selection reports gVisor on any host that has a `docker` binary.
3. **Docker-inside is a designed image and profile, not a `--privileged` flag.** The shipped image runs as a non-root user with setuid bits stripped.

---

## Problem

Today every agent phase runs as a runc (or auto-detected gVisor) container on the one Docker host that also runs the API.

- **No Docker inside.** A phase cannot run Docker or a full stack inside its workspace without host-level privilege.
- **Shared kernel.** The isolation boundary is the host kernel.
- **One host.** Flywheel saturated at 9 concurrent executions (`docs/north-star.md:11`). The targets are 100 and then 1,000 (`docs/north-star.md:12-13`), and the 1,000 tier names "Firecracker/E2B behind `IsolationBackendPort`" (`docs/north-star.md:13`).
- **Hosted sandboxes are ruled out on cost.** E2B's rate is $0.166/h at 2 vCPU / 4 GiB (`docs/research/2026-10-08-remote-executor-e2b.md:137`@b4944839), about $121 per workspace-month.

The owner wants owned bare metal where each phase gets a VM boundary, can run Docker inside, and scales by adding boxes.

**The configuration that claims to select a backend does nothing, and the host probe behind its default misreports the host.** Every point below was verified in this phase.

- `WorkspaceSettings.isolation_backend` (`packages/syn-shared/src/syn_shared/settings/workspace.py:76-79`) is never forwarded. `WorkspaceServiceConfig.from_settings` copies only image, memory and CPU (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:116-123`), so `backend` stays at its default `DOCKER_HARDENED` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:102`).
- `get_default_isolation_backend` returns `FIRECRACKER` if a `firecracker` binary is on PATH, and `KATA` if `kata-runtime` is (`packages/syn-shared/src/syn_shared/settings/workspace.py:165-169`). Nothing implements either.
- `_is_gvisor_available` checks only that a `docker` executable exists (`packages/syn-shared/src/syn_shared/settings/workspace.py:180-182`). So on any Linux Docker host without those binaries, the default is `GVISOR` (`packages/syn-shared/src/syn_shared/settings/workspace.py:171-172`), and the `DOCKER_HARDENED` branch (`:174-175`) is effectively unreachable.
- `WorkspaceSettings.docker_runtime` (`packages/syn-shared/src/syn_shared/settings/workspace.py:152-155`) has no production reader. Only `packages/syn-shared/tests/test_workspace_settings.py:140` reads it.
- **The runtime that actually runs** is decided separately. `SecurityConfig.use_gvisor=None` triggers auto-detection through `docker info` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/config.py:388-393`, `:324-338`).
- **What gets recorded** is a different value again. The workspace event records the service config's `backend` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:416-424`, `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_workspace/WorkspaceAggregate.py:341`), and the isolation handle hardcodes `isolation_type="docker"` (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:370-376`).

Settings, runtime and record are three independent answers to "what isolation runs", and nothing makes them agree. A microVM pool built on top of that would inherit the problem, so PR SYN-1 fixes it first, without changing what runs on existing installs.

---

## What exists today that the pool must fit (verified)

- **The queue:** `ExecutionRunQueue` is the only queue. `claim(host_id)` takes "the oldest claimable run within this host's own capacity" (`packages/syn-domain/src/syn_domain/contexts/orchestration/ports/ExecutionRunQueuePort.py:126-128`). `register` seeds each host's own budget row from `SYN_EXECUTION_MAX_CONCURRENT` (`packages/syn-domain/src/syn_domain/contexts/orchestration/ports/ExecutionRunQueuePort.py:100-106`).
- **ADR-072 D3:** one `execution_budget` row per executor, with a `backend` column (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:150-158`). "A second host, or a remote backend, adds a row" (`:157`). There is no reattach after an executor restart (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:55-58`).
- **Execution transport:** syn builds its own `docker exec -i`, with environment values in argv (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_helpers.py:66-73`).
- **Workspace mount:** `-v=<host dir>:/workspace:rw` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:340`).
- **Capture volume:** the capture spool is a Docker **named volume**. Recovery inspects it on the local daemon and mounts it into a runc helper container (`packages/syn-adapters/src/syn_adapters/session_inventory/docker_recovery.py:80-109`). The recovery source identity and archive are local to the process (`packages/syn-adapters/src/syn_adapters/session_inventory/runtime.py:159-164`, `:183`), with one inventory runtime per API process (`apps/syn-api/src/syn_api/_wiring_inventory.py:20-38`).
- **Provider surface:** the pinned provider's `execute` returns `ExecuteResult` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:555-563`). `teardown` and `destroy` return `None` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:382`, `:796-802`). Syn already anticipates a typed teardown report that the provider does not yet return (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:465-470`).
- **Security profile:** the production profile is `--cap-drop=ALL`, no-new-privileges, `--read-only`, tmpfs for `/tmp`, `/home/agent`, `/spool` and `/var/agentic`, and `--pids-limit=256` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/config.py:170-189`, `:340-368`). Codex images get a shipped seccomp profile plus an AppArmor profile, derived from the image label at create (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/config.py:229-271`; `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:187-193`).
- **Image user:** the omni image strips setuid/setgid bits and runs as `agent` (`lib/agentic-workspace/implementations/docker/images/omni-agent/Dockerfile:766`, `:770`).
- **Credential path:** the shared Envoy proxy is reached by Docker DNS at `http://envoy-proxy:8081` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:265-268`). Credentials are inside the sandbox today (`docs/north-star.md:183`, #1735).
- **Prior microVM material is aspirational:**
  - `docker/firecracker/README.md` names `download-kernel.sh`, `build-kernel.sh` and `build-rootfs.sh` (`docker/firecracker/README.md:70`, `:79`, `:88`), none of which exist.
  - `docs/deployment/kata-containers-integration.md:42-118` designs a `KataWorkspace` class against an architecture the repo no longer has.

---

## Comparison of the four options (source-backed where possible; unknowns stay unknown)

| Dimension | (A) E2B Embed | (B) OpenSandbox + Kata under Docker | (C) Kata/CLH under Docker, direct | (D) sysbox |
|---|---|---|---|---|
| **Isolation boundary** | Firecracker microVM | Kata VM. Kata is permitted with `docker_runtime` alone; only Firecracker needs a K8s RuntimeClass (`OpenSandbox@531700c:server/opensandbox_server/config.py:1147`, `:1182`, `:1190`); the runtime reaches Docker's host config (`OpenSandbox@531700c:server/opensandbox_server/services/docker/docker_service.py:199`, `server/opensandbox_server/services/docker/container_ops.py:395`); reviewer-read | Kata VM, same as B | **None**: shared host kernel (`sysbox@f7c4392:README.md:373`) |
| **Host requirements** | `/dev/kvm`, `/dev/net/tun`, 4 KiB pages, kernel ≥ 6.8, cgroup v2, hugepages (4 GiB default), `nbd`; several `privileged: true` services (`infra@fa7f9db:embed/compose/README.md:11-16`, `:31-45`, `:59-62`; `infra@fa7f9db:embed/compose/compose.yaml:200`, `:211`, `:283`) | `/dev/kvm` + Kata install + OpenSandbox server and DB | `/dev/kvm` + Kata install (pinned release) registered in `/etc/docker/daemon.json` | kernel ≥ 5.15 on Ubuntu 22.04 (`sysbox@f7c4392:docs/distro-compat.md:18`); **no KVM** (inferred) |
| **Docker inside** | not established | not established (same Kata guest as C) | not established; it is gated by E0b | the stated purpose (`sysbox@f7c4392:README.md:123`) |
| **Cold start** | not measured; README claims only | not measured | not measured; E0 reports it | not measured |
| **Density per host** | README claims 200/node, NBD 64 default, 3 concurrent starts (`infra@fa7f9db:embed/compose/README.md:169-183`); **not found in orchestrator source** | not measured | not measured; E0b measures it | not measured; E0b measures it |
| **Snapshot / pause** | claimed in README (`infra@fa7f9db:embed/README.md:58-59`), not traced | `docker pause`; snapshot = `docker commit`, rootfs only (in-repo review `docs/research/2026-10-12-opensandbox-source-review.md:42`@b4944839) | not used | not used |
| **Multi-host** | single node; beyond that "talk with us" (`infra@fa7f9db:embed/README.md:33-35`) | one active server per DB; process-local expiry state (`docs/research/2026-10-12-opensandbox-source-review.md:46`, `:50`@b4944839) | ADR-072: one executor and one budget row per box | same as C |
| **Exec transport** | envd (new provider and transport) | execd over HTTP, with no client idempotency key and no cancel on client disconnect (`docs/research/2026-10-12-opensandbox-source-review.md:15-21`@b4944839) | unchanged `docker exec` | unchanged `docker exec` |
| **Operational burden** | a second control plane (API, orchestrator, envd) beside ours | OpenSandbox server + DB + Kata | Kata per box + one executor per box | sysbox per box |
| **License** | Apache-2.0 (`infra@fa7f9db:LICENSE:1-3`) | Apache-2.0 | Apache-2.0 (`kata-containers@7a3711b:LICENSE:1-3`) | Apache-2.0 (`sysbox@f7c4392:LICENSE:1-3`) |
| **APSS 0.2.0 ops** | new implementation over envd | new implementation over execd; the same-key MUST is not met by execd | inherits the Docker operation implementation **once it exists** (see Dependency D-OP) | same as C |
| **Credential broker** (#1735, Envoy) | guest network unspecified | guest on the Docker network (as C) | guest on the box's Docker network; reachability of `envoy-proxy` gated by G3 | host kernel, same as today |
| **Capture recovery** | new | new | existing named-volume recovery (G4 verifies the volume persists through virtio-fs) | existing |

### Why (C) over (B), now that B's premise is corrected

B and C run the **same** Kata guest under the **same** Docker daemon, so isolation, Docker-inside and density are identical by construction. B adds:

- **a second lifecycle control plane** (OpenSandbox server, its DB, and its process-local expiry) beside `ExecutionRunQueue`, which is the thing the brief forbids rebuilding;
- **a different exec transport** (execd) in place of `docker exec`, so a new provider, new spool recovery and a new credential path;
- **an exec API without a client idempotency key**, which the APSS same-key MUST requires (`docs/research/2026-10-12-opensandbox-source-review.md:21`@b4944839).

C gets the same VM through one `--runtime` argument. *What would change this:* we want one provider that also targets hosted OpenSandbox deployments, or execd gains idempotency keys and we choose to retire `docker exec` anyway.

### Why not (A), raw Firecracker, Kata-FC, or (D) as the target

- **(A)** is single-node by its own statement, ships a second scheduler, and needs a new provider over envd. Its strengths (sub-second start, pause/resume) buy little against 100-minute phases and ADR-072's no-reattach rule (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:55-58`). *Revisit* when the remote-executor provider exists, so that one provider could serve owned Embed boxes and E2B overflow.
- **Raw Firecracker** means building a sandbox platform ourselves: a rootfs pipeline, tap networking, an in-guest exec agent, a vsock spool and the jailer. The repo's previous attempt never got past a README.
- **Kata with the Firecracker VMM** is reported to lack a shared filesystem (unverified; research Q6). That would break the `/workspace` bind mount and the named-volume spool. CLH has virtio-fs. *Revisit* if E0b shows CLH density is insufficient.
- **(D) sysbox** has no VM boundary, so it fails the owner's requirement. It is kept as E0b's comparison arm and the fallback (decision #2). It is also the only option that could give Docker-inside on flywheel, a VPS without KVM. Its maintenance status is unverified.

---

## Approach

```
ExecutionRunQueue (Postgres, ADR-072)   ← unchanged; the only queue
   │ claim(host_id) per executor, own budget row (D3)
   ├── executor on flywheel   backend=docker_hardened|gvisor (resolved)
   ├── executor on KVM box 1  backend=kata   runtime=<kata alias> → CLH
   └── executor on KVM box N  backend=kata
          │  each box: own Docker daemon, own Envoy, own capture recovery
          WorkspaceDockerProvider (docker run/exec/kill) + --runtime=<kata alias>
          ▼
       Kata VM per workspace: guest kernel, /workspace + capture volume via virtio-fs
```

### Where change comes from, and the seams

| Expected change | Where it lands |
|---|---|
| A new Kata or CLH release, or another VMM | host provisioning (`infra/`) and the Kata config; nothing above the `--runtime` argument sees it |
| A new harness CLI | agentic-workspace harness adapters, unchanged; the guest runs the same image |
| More boxes | one executor process plus one budget row (ADR-072 D3) |
| Hosted overflow later | a separate provider behind the operation contract (the remote-executor plan, not this one) |

### Dependency D-OP (not this plan's to build, but it gates production)

The APSS 0.2.0 operation contract lives in `docs/plans/20261013_provider-operation-contract.md`@b4944839 (reviewer-read). It requires:

- `start` returning on acceptance;
- same-key idempotency;
- confirmed descendant termination;
- cursor/gap observation;
- finalize-before-destroy;
- a `SupportsOperations` protocol;
- a teardown report;
- an owner-controlled operation spool (`:200`, `:205`, `:215`, `:225`, `:229`, `:300`, `:309`, `:318`@b4944839).

None of that is implemented in the pinned provider (see "What exists today").

**This plan does not implement it a second time.** It depends on that plan's *Docker* operation implementation and its production integration. Because Kata keeps the Docker API, that implementation should carry over. "Should" is a hypothesis, which is why PR KATA-CONF exists. Until D-OP lands, a Kata box may run only E0 and staging, never production phases.

### Ordered PRs

```
AW-1 ─┐
      ├─> E0a (transport spike) ─> AW-2p (disposable nested image) ─> E0b (nested + capture + density)
SYN-1 ┘                                                                    │ pass
                       D-OP (contract plan) ──────────────────────────────>├─> KATA-CONF
                       ADR-072 1.3-1.5 ───────────────────────────────────>├─> INFRA-1 ─> SYN-2
                                                                           └─> AW-2 (release) ─> SYN-3
```

#### AW-1 (agentic-workspace): one explicit runtime choice in `SecurityConfig`

- **Runtime field.** Replace `use_gvisor: bool | None` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/config.py:191-192`) with `runtime: WorkspaceRuntime | None`. `WorkspaceRuntime` is a `StrEnum` of `RUNC`, `GVISOR`, `KATA`, `SYSBOX`.
- **`None` keeps today's auto mode exactly:** runsc if Docker lists it, else runc (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/config.py:388-393`).
- **One resolver**, `resolve_runtime() -> ResolvedRuntime`, generalises `detect_gvisor` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/config.py:324-338`). It reads `docker info --format '{{json .Runtimes}}'` through the existing `_docker_info` seam (`:289-307`). It returns a frozen dataclass with:
  - `requested: WorkspaceRuntime | None`;
  - `effective: WorkspaceRuntime`;
  - `alias: str` (the name Docker registered);
  - `runtime_path: str` (the binary or shim Docker reports for that alias).
- **Fail closed.** An explicit runtime whose alias Docker does not list raises `DockerDetectionError`, and an explicit `KATA` whose registered path is not a Kata shim or runtime raises too. Neither falls back to runc. Today, `use_gvisor=True` on a host without runsc only fails later, inside `docker run`. That changes to a raise at resolution.
- **Honest scope of the check.** It proves registration and the configured binary, **not** that a guest kernel booted. That host-level VM assertion is E0's job (G1), and a runtime check after create can come later (see SYN-1).
- **Logging and metadata.** `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:231-236` logs `gvisor=`; change it to log `requested`/`effective`/`alias`. Add those to `Workspace.metadata` (`:268-274`).
- **Docstrings:** fix the gVisor-only module docstrings in `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py`.
- **Release path:** this is a Python library change consumed through the submodule. No image is needed, so there is no release-channel wait.

#### SYN-1 (syntropic137): one knob, an auto default that stays auto, a truthful record

- **Settings: auto is a value, not a guess.**
  - `WorkspaceSettings.isolation_backend` becomes `IsolationBackend | None`, default `None` (= auto). The empty-string validator also yields `None`.
  - **Delete** `get_default_isolation_backend` and `_is_gvisor_available` (`packages/syn-shared/src/syn_shared/settings/workspace.py:163-182`) and their export (`packages/syn-shared/src/syn_shared/settings/__init__.py:80`, `:117`). A VM backend is an operator decision, never inferred from binaries on PATH. The gVisor "probe" does not probe gVisor.
  - Delete the unread `docker_runtime` (`packages/syn-shared/src/syn_shared/settings/workspace.py:152-155`), and update `packages/syn-shared/tests/test_workspace_settings.py:140` and `:183-207`.
  - Regenerate `.env.example` (ADR-004).
- **Forwarding.** `WorkspaceServiceConfig.from_settings` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:116-123`) forwards the requested backend into a new field `requested_backend: IsolationBackend | None`.
- **One mapping, resolved once at service construction.** In `_create_docker_impl` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:248-254`), an exhaustive `match` on `requested_backend` builds the `SecurityConfig`:

  | Requested | `SecurityConfig.runtime` |
  |---|---|
  | `None` | `None` (auto) |
  | `DOCKER_HARDENED` | `RUNC` |
  | `GVISOR` | `GVISOR` |
  | `KATA` | `KATA` |
  | `FIRECRACKER`, `CLOUD` | raise "not implemented" at startup |

  - The match ends in `assert_never`. It matches on the **settings** enum `IsolationBackend`, whose five members are exactly these arms. `MEMORY` and `LOCAL` exist only on the domain enum (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_workspace/value_objects.py:45-46`) and are selected by `WorkspaceBackend`, not settings. So they are handled before the match, as today (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:200-203`).
  - The service then calls `resolve_runtime()` **once** and stores the result. An explicit unavailable runtime fails the process at startup, not on the first phase.
- **Record what is enforced, not what was asked.**
  - The aggregate's `backend` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:421`) becomes the domain value mapped from `resolved.effective`: runc → `DOCKER_HARDENED`, runsc → `GVISOR`, kata → `KATA`. An auto-mode install on runc therefore records `docker_hardened`, as it does today. This needs no new domain term and no dashboard change: the dashboard already maps these values (`apps/syn-dashboard-ui/src/components/WorkspaceInfoCard.tsx:88-98`).
  - `IsolationHandle.isolation_type` stops being the literal `"docker"` (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:372`) and carries the effective runtime.
  - **Not claimed:** the creation event still records the *resolved configuration* before the container exists. A post-create in-guest assertion, e.g. the kernel release differing from the host's, is a follow-up once E0 shows a cheap reliable signal.
- **Vocabulary:** add `kata` (an isolation backend: a Kata Containers VM, run through Docker's runtime seam) to `docs/architecture/orchestration-ubiquitous-language.md`, which has no entry today. **No new term "pool":** the pool is the set of executors whose budget row says `backend=kata`.

#### E0a: transport spike on one KVM box (no product code beyond AW-1 + SYN-1)

Gates G0, G1, G3 and a non-nested G4 (see Verification). **E0a is a feasibility spike, not APSS acceptance.** It proves the Docker transport works over a Kata guest. It does not prove the operation contract.

#### AW-2p (agentic-workspace, disposable prototype, NOT released)

This is a locally built nested-Docker image and profile used only on the E0 box. It exists so that E0b tests the image SYN-3 would actually ship, not an ad hoc privileged container.

**Bootstrap model chosen: root bootstrap, then drop to `agent`.**

- The variant's `ENTRYPOINT` is a small root wrapper. It:
  1. mounts the writable paths;
  2. starts `dockerd` as root, with `--data-root=/var/lib/docker` and a socket at `/run/docker.sock`, group `docker`;
  3. waits for the socket (bounded, failing the workspace on timeout);
  4. `exec`s the existing entrypoint as `agent` via `setpriv --reuid=agent --regid=agent --init-groups`.
- `agent` is in group `docker`, which is **root-equivalent inside the guest**. That is accepted only because the VM is the boundary, and is why nested Docker is refused outside `KATA`/`SYSBOX`.
- **Rejected: rootless dockerd.** It needs setuid `newuidmap`/`newgidmap`, which the image strips (`lib/agentic-workspace/implementations/docker/images/omni-agent/Dockerfile:766`), and nested user namespaces inside a guest, which adds an unmeasured failure mode for no isolation gain over the VM.

**Profile `SecurityConfig.nested_docker_vm()`.** It raises unless the effective runtime is `KATA` or `SYSBOX`, so privileged runc can never be produced.

| Setting | Production profile | `nested_docker_vm()` |
|---|---|---|
| Capabilities | `--cap-drop=ALL` | `--privileged` (guest-scoped under Kata, **verified by G2, not assumed**) |
| no-new-privileges | on | on (the wrapper only *drops* privilege) |
| Root filesystem | `--read-only` | stays `--read-only` |
| Writable paths | tmpfs `/tmp`, `/home/agent`, `/spool`, `/var/agentic` | the same, plus: `/var/lib/docker` on a per-workspace **block-backed volume** (overlay2 on virtio-fs is not assumed to work; G2 decides); tmpfs `/run`, `/var/run`, `/etc/docker` |
| PIDs | `--pids-limit=256` | raised to a value G2 measures |

- **Shutdown:** `docker stop` sends SIGTERM to the wrapper. The wrapper stops the agent process tree first, then runs `docker ps -q | xargs -r docker kill` inside the guest, then stops dockerd. Destroy kills the VM regardless. Finalize-before-destroy (D-OP) runs *before* this.
- **Codex:** the image label still derives the Codex policy (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:187-193`). Under Kata the host seccomp/AppArmor do not reach the guest (see Security policy), so the enforced policy has to be set in the guest and tested (G5).
- **Known unknown:** with Docker (non-CRI), containerd's `privileged_without_host_devices` option is not available. Kata may therefore pass **host devices** into a privileged guest. G2 checks this explicitly. If it does, the profile uses explicit capabilities (`SYS_ADMIN`, `NET_ADMIN`, `MKNOD`, and the like) plus a device allow-list instead of `--privileged`.

#### E0b: nested Docker + capture + density, both harnesses

G2, G4 (nested), G5 and Stage 2 density, all with the AW-2p image and profile running through Syntropic137.

**Decision point after E0b:**
- If everything passes, continue.
- If Kata fails G1, G2 or G3 and host configuration cannot fix it, stop and return to the human with the sysbox arm's numbers (decision #2).

#### KATA-CONF (agentic-workspace, after D-OP lands)

Run the operation contract's conformance suite against `WorkspaceDockerProvider` with `runtime=KATA` on a KVM host. It must cover:

- concurrent repeated `start` with the same key (exactly one launch);
- lost response, then retried `start`;
- a changed spec under the same key (conflict);
- expired and foreign cursors;
- stream disconnect mid-observe;
- cancel with **descendant** processes (a `setsid` grandchild must be confirmed dead);
- finalization failure that retains output;
- destroy retry after a partial failure.

Add a Kata row to `lib/agentic-workspace/tests/conformance/COVERAGE.md` stating the *enforced* security profile per runtime, not the requested one.

CI on a KVM runner would need a workflow change. This workspace cannot push one, so it would be delivered as a patch artifact for the human.

#### INFRA-1 (after E0b passes): KVM executor host provisioning

- A pinned, idempotent host script under `infra/`:
  - installs Kata at a pinned release with CLH as the configured hypervisor;
  - registers a runtime alias in `/etc/docker/daemon.json` **without** changing `default-runtime` (control-plane containers and the capture-recovery helper stay on runc);
  - sets the guest-seccomp policy chosen in "Security policy";
  - runs `kata-runtime check`.
- Delete `docker/firecracker/`, which advertises scripts that do not exist.
- Replace `docs/deployment/kata-containers-integration.md` with the real procedure.
- ADR: "Owned-host workspace isolation is Kata (CLH) under Docker", citing E0's report.

#### SYN-2 (blocked on ADR-072 items 1.3-1.5 and D-OP): executors on the KVM boxes

- **Executor role.** Each box runs the ADR-072 executor role (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:69`), registering with `backend` from the resolved runtime into `execution_budget.backend` (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:152-153`).
- **Capacity** comes from `SYN_EXECUTION_MAX_CONCURRENT`, sized from E0b's measured N. "A concurrency limit that is a hard-coded constant is a defect" (`docs/north-star.md:228`).
- **Capture ownership, made explicit:**

  | Concern | Owner on each box |
  |---|---|
  | Recovery tick | the **executor process on that box**. It constructs the existing `DockerSpoolRecovery` (`packages/syn-adapters/src/syn_adapters/session_inventory/runtime.py:183`) against its *local* daemon. No new recovery adapter |
  | Source identity | a per-box `source_instance_id` (`packages/syn-adapters/src/syn_adapters/session_inventory/runtime.py:161-164`), so `PostgresCaptureSpools` rows are scoped to the box that holds the volume |
  | Archive | the archive must be reachable by whichever process serves transcripts. Today it is `LocalSessionTranscriptArchive(settings.archive_dir)` (`:159`), which is local, so SYN-2 must either point every box at shared storage or upload archived transcripts to object storage. Which one is decision #8 |
  | Retained volumes | stay on the box until that box's executor releases them; a dead box's volumes are recoverable only when the box returns |

  Tests:
  - recovery on box B refuses a spool registered to box A's `source_id`;
  - after box A's executor dies and restarts, its retained volume is recovered and the transcript archived;
  - the archive is readable from the API host.
- **Credentials:** each box runs its own Envoy and token injector, as flywheel does. The guest joins the box's Docker network; G3 verifies it.
- **If ADR-072 slips:** KVM boxes can run as additional complete single-node stacks (decision #3).

#### AW-2 (agentic-workspace, image + release channel): nested Docker for real

- Promote AW-2p's wrapper, image variant and `nested_docker_vm()` profile, with unit tests.
- **Delivery cost:** merge → image build → protected `release` channel → `PINNED_DIGESTS` bump here.

#### SYN-3 (syntropic137): select the nested image and profile on `kata` executors

No per-phase routing (decision #4).

#### Later: #1735 (no credential in the sandbox)

Not newly required, since credentials are in the sandbox today (`docs/north-star.md:183`). But root-in-guest with inner containers widens what can read them (decision #5).

### Security policy under Kata (corrected from the first draft)

- **Guest seccomp is off by default.** Kata's pinned CLH config template documents disabled guest seccomp as the default (`kata-containers@7a3711b:src/runtime/config/configuration-clh.toml.in:388`, reviewer-read).
- **Consequence:** under Kata, neither Docker's default seccomp profile nor the shipped Codex profile (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/config.py:229-254`) is enforced on agent processes unless the host config enables guest seccomp. Host AppArmor confines the VMM process, not guest processes.
- **Intended policy:**
  1. The VM is the primary boundary.
  2. INFRA-1 sets `disable_guest_seccomp = false`, so the requested profile is passed to and enforced by the Kata agent in the guest.
  3. Codex images keep the shipped Codex seccomp profile.
  4. AppArmor is recorded as "not enforced in guest" in the conformance row, not silently claimed.
- **Gate G5 tests this behaviourally, not by reading `Seccomp:`:**
  - a syscall that Docker's default profile denies (`keyctl` or `add_key`) fails with `EPERM` in a non-Codex workspace;
  - Codex's bubblewrap sandbox (`codex sandbox linux -- true`, or the existing probe in `packages/syn-domain/src/syn_domain/contexts/orchestration/`) succeeds in a Codex workspace.

  If enabling guest seccomp breaks either, the human decides between the two (decision #7).

### Maintenance cost

- **Code:** one runtime enum and resolver, one settings `match`, one profile with a guard, one image variant with a root wrapper. No new provider class, transport, spool or recovery adapter.
- **Operations:** a pinned Kata version per box and its upgrade cadence, host kernel and KVM upkeep, one executor plus Envoy per box, per-box disk monitoring (inner images on top of 1-3 GB per phase, `docs/north-star.md:76`), and per-box capture retention.
- **The long-term risk is Kata's Docker (non-CRI) path.** Its maintainers centre containerd/CRI. If Docker support regresses, moving to containerd is **a separate transport implementation, not a command prefix**: syn builds `docker exec` itself (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_helpers.py:66-73`), and recovery calls `docker volume`/`run`/`exec`/`rm` directly (`packages/syn-adapters/src/syn_adapters/session_inventory/docker_recovery.py:83`, `:92`). It would be planned as its own decision then, not pre-built now. E0's G1 and each Kata upgrade are the early warning.

---

## Risks

| Risk | Signal that it broke |
|---|---|
| Kata's Docker path rejects the hardened `docker run` args, or Docker's embedded DNS is unreachable from the guest | G1/G3 fail; in production, provision failures concentrated on `backend=kata` |
| Guest seccomp off, so requested profiles are not enforced | G5; the conformance row states the enforced profile |
| Privileged Kata guest receives host devices (no `privileged_without_host_devices` on the Docker path) | G2 device check; fallback is explicit capabilities |
| overlay2 does not work for inner Docker on virtio-fs | G2 storage-driver check; the block-backed `/var/lib/docker` volume is the default design |
| virtio-fs makes git/pnpm on `/workspace` slow | E0b wall-time ratio vs runc |
| Guest memory not returned during a 100-minute phase | E0b per-VM RSS **slope** over a full-lifetime cohort |
| Nested Docker fills disk | `df`; ENOSPC on create; E0b disk per workspace |
| Root in guest widens credential reach | owned by #1735; decision #5 |
| ADR-072 1.3-1.5 or D-OP slip | SYN-2/KATA-CONF cannot start; the stopgap is decision #3, and **no production Kata phases without D-OP** |
| Explicit `kata` silently runs as runc | AW-1 fail-closed tests; G1 host-level VM assertion; recorded `isolation_type` ≠ configured |

---

## Verification

### Unit tests

Each test states whether it fails if its change is reverted.

**AW-1**, in agentic-workspace's Python tests beside the `SecurityConfig` tests, stubbing `_docker_info` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/config.py:289-307`):

1. **Kata registered.** `runtime=KATA`, with Docker listing a kata alias whose path is a Kata shim: args contain exactly one `--runtime=<alias>`. *Reverts → fails.*
2. **Kata missing.** `runtime=KATA`, with Docker listing only runc: raises. *Catches a silent runc fallback.*
3. **Alias without Kata.** `runtime=KATA`, with an alias named `kata` whose path is `runc`: raises. *Catches "name ≠ isolation".*
4. **Auto mode.** `runtime=None` with runsc listed → `--runtime=runsc`; with only runc → no `--runtime`. *Guards the existing default. It passes today too, so it is labelled a regression guard, not a change test.*
5. **gVisor missing.** `runtime=GVISOR` with no runsc: raises at resolution. *Reverts → fails, because today it emits the arg and fails later in `docker run`.*

**AW-2p/AW-2:**

6. `nested_docker_vm()` with effective `RUNC` raises; with `KATA` it emits `--privileged` and keeps `--read-only` and no-new-privileges.

**SYN-1**, `unit`-marked, under `packages/syn-shared/tests/` and `packages/syn-adapters/`:

7. **End-to-end, runc-only host, no override.** Settings → `from_settings` → `WorkspaceService.create`, with `docker` on PATH, no env override, and Docker info listing only runc. The service builds `SecurityConfig.runtime is None`, `docker run` args carry **no** `--runtime`, and the recorded backend is `DOCKER_HARDENED`. *This is the regression the first draft would have introduced: it fails against a SYN-1 that forwards today's `GVISOR` default.*
8. **Explicit gVisor, not registered.** `SYN_WORKSPACE_ISOLATION_BACKEND=gvisor` with runsc not listed: service construction raises.
9. **Explicit Kata.** `SYN_WORKSPACE_ISOLATION_BACKEND=kata` with the kata alias listed: `SecurityConfig.runtime == KATA`, the recorded backend is `KATA`, and `isolation_type` is `kata`. *Today the setting is dropped (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:116-123`), so this fails on revert.*
10. **Not implemented.** `firecracker` or `cloud` raises at construction.
11. **No PATH inference.** With `/dev/kvm` and a `firecracker` binary faked on PATH, the default is `None` (auto). *Fails against today's `packages/syn-shared/src/syn_shared/settings/workspace.py:165-167`.*
12. **Enum guard.** Every `IsolationBackend` value maps to an `IsolationBackendType`, and the effective-runtime → domain mapping is total. *Labelled a guard: the subset relation already holds on the baseline.*

Gates from CLAUDE.md "Verification gates":

```
just preflight-agent
uv run pytest -m unit -q
```

plus agentic-workspace's own Python test target.

### E0: the measured-proof experiment (one box)

**Box:** one bare-metal KVM machine (Hetzner AX-class is the brief's candidate). **Not flywheel:** it is a Contabo VPS, and Contabo documents nested KVM for VDS only. The report records model, cores, RAM, disk, price, and the Kata, CLH, kernel and Docker versions.

**E0a gates (manual on the box, then through Syntropic137):**

| Gate | Assertion |
|---|---|
| G0 host | `test -c /dev/kvm`; `kata-runtime check` exits 0; `docker info` lists the kata alias with the Kata shim path |
| G1 transport + VM | `docker run` with the **exact** args AW-1 + `SecurityConfig.production()` emit, with `--runtime=<alias>` and the pinned workspace image, starts. **VM assertion:** `uname -r` in the container ≠ the host's, and a CLH process for that sandbox exists on the host. `docker exec -i` streams stdin/stdout. A file written to `/workspace` is visible on the host. `docker kill` ends it in ≤ 10 s. A `setsid` grandchild is killable from a fresh `docker exec` |
| G3 credentials | from the guest: `getent hosts envoy-proxy` resolves, and a model-API request through `$SYN_PROXY_URL` succeeds with no model credential in the guest env for that call |
| G4a capture, non-nested | one real phase with `SYN_WORKSPACE_ISOLATION_BACKEND=kata`. The capture **named volume** is written from the guest and visible on the host. `kill -9` the API mid-phase; after restart, recovery archives the transcript and the #1550 detector is clean |

**E0b gates (AW-2p image and profile through Syntropic137, for Claude Code and Codex each):**

| Gate | Assertion |
|---|---|
| G2 nested Docker | inside the workspace as `agent`: `docker info` reports `overlay2` (not `vfs`); `docker run hello-world` works; `docker compose up` of syntropic137's own stack reaches healthy. **Device check:** no host block devices in the guest's `/dev` (compare `lsblk` with the host's) |
| G4b capture, nested | the same as G4a, in a workspace whose inner compose stack is running when the API is killed; the inner stack is gone after destroy |
| G5 security | as in "Security policy": a denied syscall fails in non-Codex; Codex's bubblewrap probe succeeds in Codex |

**E0b Stage 2: density.**

- **Arms**, each run separately on the same box with the same image digest, `--memory`, `--cpus` and pids limit: **runc** (baseline, non-nested only), **sysbox**, **kata-CLH**.
- **Workloads:**
  - **W1**, an ordinary phase: `sdlc-implement-v3` on one fixed repo and commit, nested Docker available but idle.
  - **W2**, the product the owner asked for: the same phase, where **every** active workspace also brings up a fixed inner compose stack (syntropic137's own `docker compose up` to healthy) and holds it for the phase. runc runs W1 only, and the W2 comparison is kata vs sysbox.
  - Token-free recorded playback (#1717) if it has landed; otherwise real model calls with approval (decision #6).
- **Ramp:** N = 10, 20, 40, then +10, all admitted within 5 minutes (`docs/north-star.md:16`). Each step is held for **30 minutes** of active phases (`docs/north-star.md:17`).
- **Stopping rule:** stop the ramp at the first N that fails the pass bar, or at host CPU ≥ 95% or memory ≥ 90% for 5 minutes. The max passing N is the step before.
- **Full-lifetime cohort:** separately, at 0.8 × the max passing N, run one cohort where every phase runs to completion (≥ 100 min). This cohort supplies completed-phase wall p50/p95 and the memory-growth measurement.
- **Deploy under load:** during one held step per arm, deploy a new API/executor generation (ADR-072 overlap). Zero lost or orphaned runs is required (`docs/north-star.md:20`).
- **Repeats:** each arm's max-N step and full-lifetime cohort run **3 times**; report the median and range.

Per arm, workload and N, record:

- create time p50/p95;
- phase wall p50/p95;
- host CPU utilisation and steal;
- host RSS;
- per-VM RSS sampled every 60 s;
- disk per workspace;
- lost and orphaned runs;
- the #1550 result;
- event counts vs transcripts.

**Pass bar.** It is relative to runc, so it holds whatever the absolute numbers are.

1. G0-G5 pass for both harnesses.
2. **Correctness at every N reached, including the deploy:** zero lost or orphaned executions, #1550 clean, and per-run event counts equal to transcripts (`docs/north-star.md:18-21`).
3. **Density (W1):** kata max passing N ≥ 0.8 × runc max passing N. A passing N has every phase completing inside its deadline and p95 dashboard reads < 500 ms.
4. **Density (W2):** reported for kata and sysbox, and used to size `SYN_EXECUTION_MAX_CONCURRENT` for `kata` boxes. It is not gated against runc, which cannot run W2.
5. **Speed:** in the full-lifetime cohort, kata completed-phase wall p50 ≤ 1.15 × runc's at the same N (W1).
6. **Memory stability:** per-VM RSS has no sustained growth. Over the last 60 minutes of each phase in the full-lifetime cohort, a least-squares slope ≤ 1% of the VM memory cap per 10 minutes. "Stayed under the cap" is **not** the criterion.
7. **Cold start is reported, not gated.** If p95 create exceeds 60 s, it is flagged.

The thresholds (0.8, 1.15, 1%/10 min, 3 repeats) are proposals the human ratifies (decision #1).

**Report:** `docs/research/<date>-selfhosted-microvm-e0.md`, with the raw tables, versions and box spec. The INFRA-1 ADR cites it, and the brief's measured inputs are re-recorded there with a citable source (#1716).

---

## Out of scope

- The executor/API split, multi-host placement, heartbeat and fencing (ADR-072 1.3-1.5, #1734). This plan consumes them.
- The APSS operation implementation itself (D-OP). This plan depends on it and runs its conformance under Kata.
- Any new scheduler, queue, or claim predicate.
- Hosted sandboxes and non-Docker transports.
- #1735 and the Envoy bucket (#1720). One Envoy per box makes the "global" bucket per-box, which only relaxes it.
- Snapshot, pause/resume and warm pools (no-reattach rule; 100-minute phases).
- Kubernetes.
- Firecracker in any form, until E0b shows CLH density is insufficient.
- `.github/workflows/` changes (a patch artifact if a KVM CI runner is wanted).

---

## Needs a human decision

1. **Ratify the E0 pass bar:** density ≥ 0.8 × runc (W1), wall ≤ 1.15 × runc, memory slope ≤ 1% of cap per 10 min, 3 repeats, and the ramp and stopping rule.
2. **If Kata fails G1, G2 or G3:** accept sysbox (no VM boundary), or stop and revisit Kata-FC with a block-device workspace design.
3. **If ADR-072 1.3-1.5 are not ready when E0b passes:** run KVM boxes as extra full single-node stacks (separate dashboards, no shared queue)? Production phases still wait for D-OP either way.
4. **Mixed fleet:** a phase that needs Docker could be claimed by flywheel. Options:
   - (a) a homogeneous fleet: retire flywheel as an executor (recommended);
   - (b) an ADR-072 amendment adding a capability predicate on `claim`;
   - (c) fail fast where nested Docker is unavailable.
5. **Nested Docker before #1735?** That means agent root in a guest holding a GitHub installation token.
6. **Buy or rent the E0 box,** and approve token spend if #1717 playback has not landed.
7. **If enabling guest seccomp breaks Codex's sandbox or the nested daemon:** run with guest seccomp off (VM-only boundary, recorded as such), or block until a guest profile works.
8. **Archive location for multi-box capture:** shared filesystem, or upload to object storage.
9. **Confirm the brief's cost figures.** E2B ~$119/month, Hetzner AX $7-23/workspace-month and EPYC 7763 ~$4k / ~60 phases are not in the repo. E0 supplies N per box; the price is the operator's to state.

---

## Open questions (do not block starting AW-1/SYN-1/E0a; they decide E0's outcome)

- **Is APSS EXP-V1-0006 0.2.0 merged upstream, and does pin `18d55b23` (`lib/agentic-workspace/Cargo.toml:24`) include it?** The schemas being available does not change D-OP: the Python Docker operation implementation is what gates production.
- **Kata-FC shared filesystem (research Q6).** Relevant only if CLH density fails.
- **sysbox maintenance status since the Docker acquisition (research Q9).** Matters only if decision #2 picks it.
- **Does a privileged Kata guest under Docker receive host devices?** Answered by G2.

---

## Review disposition

| finding | accepted / rejected | what changed |
|---|---|---|
| **B1** Option B rejected on a false premise (OpenSandbox runs Kata under Docker without K8s) | **accepted** | The research's own wording ("gVisor, Kata or Firecracker, with **Firecracker** mapped to a Kubernetes RuntimeClass") already supported the narrower reading; the first draft over-generalised it. I could not open OpenSandbox in this phase, but the reviewer cites pinned lines and nothing on disk contradicts them. B is now "OpenSandbox + Kata under Docker" in a full A-D comparison table. C still wins, on the second control plane, the execd transport and execd's missing idempotency key, not on Kubernetes |
| **B2** APSS schema ≠ Docker operation implementation | **accepted** | Verified: `execute` returns `ExecuteResult` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:555-563`), `teardown` returns `None` (`:796-802`), and syn still awaits a typed report (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:465-470`). Added dependency D-OP (production gated on it), renamed E0's first stage a "transport spike, not APSS acceptance", and added PR KATA-CONF with the reviewer's eight conformance cases |
| **B3** SYN-1 breaks runc-only Docker hosts | **accepted** | Verified: `_is_gvisor_available` only checks for a `docker` binary (`packages/syn-shared/src/syn_shared/settings/workspace.py:180-182`), so the default is `GVISOR` on runc hosts (`:171-172`). SYN-1 now makes auto an explicit `None`, deletes the misleading probe and the PATH sniffing, resolves once at startup, and records the *effective* runtime. Added end-to-end test 7 (runc-only, no override → no `--runtime`) and test 8 (explicit gVisor unavailable → refuse) |
| **B4** Docker-inside under-specified; E0 not representative | **accepted** | Verified: `USER agent` and setuid stripping (`lib/agentic-workspace/implementations/docker/images/omni-agent/Dockerfile:766`, `:770`). Chose a root bootstrap that drops to `agent`, rejected rootless with reasons, specified socket, writable paths, storage, shutdown and the profile table. Split E0 into E0a and E0b around a disposable AW-2p image, run through Syntropic137 for both Claude Code and Codex, with nested Docker and capture gated together (G4b). Added the host-device risk on the Docker (non-CRI) path |
| **I1** Density experiment does not measure the requested workload | **accepted** | Added W2 (every workspace runs an inner stack), a full-lifetime cohort for wall time and memory, identical per-arm settings, 3 repeats, a stopping rule, and a deploy under load. Replaced "below the cap" with an RSS slope criterion |
| **I2** Runtime alias registration ≠ isolation evidence | **accepted** | Verified the hardcoded `isolation_type="docker"` (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:372`). The resolver checks the alias's runtime path (test 3), G1 adds a host-level VM assertion (guest kernel ≠ host, CLH process present), SYN-1 records the effective runtime in the aggregate and the handle, and the plan states what is still only configuration (the pre-provision event) |
| **I3** Enum subset test already passes; `MEMORY` missing from `assert_never` | **accepted** | Verified: the settings enum (`packages/syn-shared/src/syn_shared/settings/workspace.py:46-53`) ⊂ the domain enum (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_workspace/value_objects.py:37-46`). The heading now says each test states whether it fails on revert, and tests 4 and 12 are labelled guards. The match is now on the settings enum (exactly five arms), with `MEMORY`/`LOCAL` handled before it via `WorkspaceBackend` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:200-203`) |
| **I4** Kata guest seccomp default is in source; gate needs a policy | **accepted** | Took the reviewer's pinned citation for `disable_guest_seccomp` (not re-readable here). Added a "Security policy under Kata" section: guest seccomp is enabled in INFRA-1, Codex's profile is kept, AppArmor is recorded as not enforced in the guest, and G5 is a behavioural test (a denied syscall plus Codex's bubblewrap probe) with decision #7 if they conflict |
| **I5** Multi-host capture ownership implicit | **accepted** | Verified the local-daemon recovery and per-process source id (`packages/syn-adapters/src/syn_adapters/session_inventory/docker_recovery.py:80-109`; `packages/syn-adapters/src/syn_adapters/session_inventory/runtime.py:159-164`, `:183`; `apps/syn-api/src/syn_api/_wiring_inventory.py:20-38`). SYN-2 now has an ownership table (recovery tick, source id, archive, retained volumes) that reuses `DockerSpoolRecovery`, with wrong-host refusal and post-loss recovery tests. The archive location is decision #8 |
| **I6** Abbreviated citations; nerdctl is not a prefix | **accepted** (one correction) | Every local citation is now root-relative. The mount line is `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:340`, not `:339` as the reviewer gave: 339 is the `# Workspace mount` comment and 340 is the `-v` emission. The nerdctl fallback is restated as a separate transport decision, citing `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_helpers.py:66-73` and `packages/syn-adapters/src/syn_adapters/session_inventory/docker_recovery.py:83`, `:92` |

No finding was rejected. Each blocker was checked against the working tree and held up. B1 and I4 cite upstream sources that are not on disk in this workspace; they were accepted because the reviewer gives pinned lines and the research's own wording agrees, and that limit is stated in the rows above.

## Readiness

Ready to implement AW-1, SYN-1 and the E0a spike now. Every step after E0a is blocked on human decisions #1 (pass bar) and #6 (provide the KVM box and token budget). Production Kata phases are further blocked on D-OP (the provider-operation-contract plan's Docker operation implementation) and ADR-072 items 1.3-1.5.


## Implementation log

- 2026-10-13: AW-1 merged as AgentParadise/agentic-workspace#48 (`0f48e8c`). Second verifier approved with one waived cross-repo break: syntropic137 `packages/syn-adapters/tests/test_docker_capture_recovery.py:74` uses `SecurityConfig(use_gvisor=False)`; **SYN-1's submodule bump MUST change it to `runtime=WorkspaceRuntime.RUNC`**. Accepted low: auto mode no longer selects a runsc alias whose path is a wrapper script, or a `gvisor` alias with no path. E0 operators must register Kata by path, not runtimeType only.
