# Remote workspace executor (E2B first): research and build plan

Date: 2026-10-08. Status: research and build plan, input to epic
[#1612](https://github.com/syntropic137/syntropic137/issues/1612) and
[ADR-072](../adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md).
Docs only: no production code, no ADR edit, no vocabulary edit, no issues
filed. Code citations are against `main` at `38d4db687`, with the
agentic-workspace submodule at `5c4e5595`.

Question: what does it take for work to overflow onto cloud sandboxes (E2B
first) when local hosts are full, without losing observability, restart
safety or the credential posture? What does it cost against the
alternatives, and in what order should it be built?

The short answer: a remote tier is **one more kind of Executor under
ADR-072**, not a new architecture. It needs three provider capabilities in
agentic-workspace, one composition point per backend, a credential policy
enforced by the executor, durable capture routing and a recovery capability
that is separate from provisioning. It carries no real agent work until
[#1735](https://github.com/syntropic137/syntropic137/issues/1735) ("no
credential inside a remote sandbox") is solved. Until then it can carry only
scripted runs. At 100 concurrent, more owned Docker hosts are the base and a
remote tier is a burst tier. Both recommendations are conditional on
measurements that do not exist yet
([#1716](https://github.com/syntropic137/syntropic137/issues/1716)).

## 0. Relationship to #1612 and ADR-072

ADR-072 is **Accepted** and adopts #1612 Step 2. It already holds the
placement machinery:

- one `execution_budget` row per executor, with a `backend` column
  (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:150-161`,
  `backend` at `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:153`);
- a single-transaction claim (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:163-179`);
- releases fenced by a compare-and-set (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:181-201`);
- fencing and reaping (D5, `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:265-277`).

It is **not implemented**: no `ExecutionHost` or `ExecutionRunQueue` exists in
any `.py` file (`git grep -nE "ExecutionHost|ExecutionRunQueue" -- '*.py'`
returns nothing). So this doc treats the remote tier as one more kind of
Executor under ADR-072. It cites ADR-072 by decision number (D3, D4, D5, D6,
D10) and does not restate its claim, lease or fence semantics.

This doc corrects or refines #1612 and the brief in eight places:

| # | Correction | Corrects | Evidence |
|---|---|---|---|
| C1 | `agent-net` is not internal in production, so local workspace egress is open. E2B's `allow_out` would be stricter than local, not parity. Tracked in [#1794](https://github.com/syntropic137/syntropic137/issues/1794), "security: agent-net is not internal in production; workspaces have direct internet egress, contrary to the code comment". | #1612 inventory row 15 and Step 9, which say `internal: true` | `docker/docker-compose.syntropic137.yaml:674-676` (`agent-net: null`, while `docker-proxy` is `internal: true`). The comment at `docker/sidecar-proxy/envoy.yaml:106-110` records that the pypi and npm passthrough hosts were removed and agents do not set `HTTP_PROXY`, so Envoy is not an egress gate either. The "cannot reach the internet directly" comment at `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:219-221` is false. |
| C2 | `/spool` is a named volume, not tmpfs. An explicit mount removes the matching `--tmpfs`. | refines #1612 Step 8 | `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:49`, `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:310-328` |
| C3 | E2B concurrency add-ons: Pro+ (600) is +$500/mo, Pro++ (1,100) is +$1,000/mo. #1612 says 1,100 costs a $500 add-on. | #1612 cost section (body line 266) | [E2B pricing](https://e2b.dev/pricing), accessed 2026-10-08 |
| C4 | `read_file` already exists on the provider Protocol, but it takes a path relative to the workspace root and returns text. Artifacts, the spool and the manifest still need a new binary, absolute-path `read_files`. | refines #1612 Step 7 | `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/base.py:201-218` |
| C5 | Eval verify is not credential-free. It runs a Claude agent and clones repos. | the brief | `workflows/evals/verify-pinned-sonnet/workflow.yaml:11` (`requires_repos: true`), `workflows/evals/verify-pinned-sonnet/workflow.yaml:51-53` (`provider: claude`); `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:252-255` |
| C6 | The credential gate is #1735. [#724](https://github.com/syntropic137/syntropic137/issues/724) is only the Claude API-key sidecar spike. | #1612 and the brief | `docs/north-star.md:182`, `docs/north-star.md:215` |
| C7 | A Scripted Agent is not a workflow provider. The stub image replaces the CLI, and its profile still names `claude` or `codex`. Nothing in production reads the profile today. | the earlier plan, not #1612 | `packages/syn-perf/src/syn_perf/loadtest/scripted_agent_profile.py:3-8`, `packages/syn-perf/src/syn_perf/loadtest/scripted_agent_profile.py:37-38`, `packages/syn-perf/src/syn_perf/loadtest/scripted_agent_profile.py:130`; `packages/syn-shared/src/syn_shared/agents.py:24`, `packages/syn-shared/src/syn_shared/agents.py:27`, `packages/syn-shared/src/syn_shared/agents.py:253-269` |
| C8 | Proposed amendment: the ADR-072 D5 fence guard must require the fencing executor to hold recovery access to the dead owner's backend (decision 8). | extends ADR-072 D5 and #1612 | `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:268`, `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:274-276`: any live executor may fence, and the reap removes containers by `syn.host_id`; nothing checks the backend |

The capture design below **keeps** #1612 Step 8 (decision 7). An earlier
draft of this plan read the spool only at teardown and recovered only from a
live sandbox. That silently departed from Step 8 and is withdrawn.

## 1. What a workspace needs from its host

One row per need, with E2B's verdict: **provides**, **cannot**, **must not**,
or **differently**.

| Need | Where today | E2B verdict |
|---|---|---|
| Image: `node:22-slim`, `USER agent`, entrypoint, CLIs baked in | `lib/agentic-workspace/implementations/docker/images/claude-cli/Dockerfile:66`, `lib/agentic-workspace/implementations/docker/images/claude-cli/Dockerfile:436`, `lib/agentic-workspace/implementations/docker/images/claude-cli/Dockerfile:474` | Differently. A template is built from the pinned digest ([E2B base image](https://e2b.dev/docs/template/base-image), accessed 2026-10-08, documents `from_image`). Cosign verification (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:321`) moves to template-build time and is recorded against the template. Private GHCR digests are not verified (Q5). |
| Image manifest recorded on the Workspace event | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:163-172` (reads Docker `_active_workspaces`, calls `exec_run`), consumed at `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:220-226` | Differently. Read through the provider. Today an E2B workspace would silently record `None`, losing image provenance in a Lane 1 event. |
| Hardening: cap-drop, read-only root, tmpfs, pids limit | `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/config.py:171-189` | Differently. The microVM is the boundary. In-VM read-only root and tmpfs are not documented in the pages read (Q5). This doc does not claim parity. |
| Codex bwrap: seccomp plus host AppArmor | `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/config.py:194-205`; `packages/syn-adapters/src/syn_adapters/workspace_backends/host_security.py:26-43` | Cannot, as specified. Whether bwrap works in the VM is unknown (Q4). Claude-only until smoke-tested. |
| Capture spool `/spool` as a named volume | `packages/syn-adapters/src/syn_adapters/session_inventory/workspace_capture.py:36-46`; `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:310-328` | Differently. The spool is a directory on sandbox disk, retained by pausing the sandbox, not by a volume (decision 7). |
| Spool recovery after a crash | `packages/syn-adapters/src/syn_adapters/session_inventory/runtime.py:183` (Docker only); `packages/syn-adapters/src/syn_adapters/session_inventory/recovery_worker.py:45-48`, `packages/syn-adapters/src/syn_adapters/session_inventory/recovery_worker.py:85-116`; the spool model has no backend or owner (`packages/syn-domain/src/syn_domain/contexts/agent_sessions/ports/SessionCaptureSpoolPort.py:14-18`) | Differently. Durable routing to a paused sandbox; the existing execute-based readers are reused (decision 7). |
| Artifact collection | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/managed_workspace.py:249-254` -> `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:582-583` -> host path, empty list if there is none (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter_copy.py:158-160`) | Differently. Read through the provider's `read_files`. Today E2B output would **silently vanish**. |
| Agent stream: `docker exec -i` with the announce wrapper, stderr merged, exit code and signal diagnosis | `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_helpers.py:44-73`; `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:176-212`; `last_exit_code` port at `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ports.py:224-226` | Differently. An E2B command session. Only the inner sandbox argv (wrapper plus command) is reused (decision 4). |
| Lost-status and signal-death diagnosis on short commands | `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:534`, `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:546-552` (by container name) | Differently. The provider supplies its own diagnosis, or reports explicitly that it has none. |
| Envoy on `agent-net` (`envoy-proxy:8081`), required by `_build_agent_env` | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:259-262`; `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:226-232` | Cannot. Envoy is not reachable from E2B. Needs a public, authenticated ingress, after #1735. |
| Claude credential in agent env | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:216-271`, called at `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:760` | Must not. Gated on #1735. |
| Codex `auth.json`; GitHub `~/.git-credentials` and `hosts.yml`, staged even when `clone_repos: false` | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:140-169`, `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:512-531`; `packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:208-213`, `packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:500-532` | Must not. Gated on #1735. |
| Session-store write token in container env | `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:237-257`, `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:306-308` | Must not while it is a raw credential. Covered by the credential policy (decision 5). |
| Egress policy | `docker/docker-compose.syntropic137.yaml:674-676` (open, C1, #1794) | Provides more: `allow_out` and `deny_out`; domain allowlists only together with deny-all ([E2B internet access](https://e2b.dev/docs/sandbox/internet-access), accessed 2026-10-08). |
| CPU, RAM, disk | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:103-104`, `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:116-122` | Provides: up to 8 vCPU and 8 GiB, 10 GiB disk on Hobby and 20 GiB on Pro ([E2B billing and limits](https://e2b.dev/docs/billing), accessed 2026-10-08). |
| Orphan reap, with the unpushed-work guard run inside each orphan | `apps/syn-api/src/syn_api/services/reconciliation.py:348-376`, `apps/syn-api/src/syn_api/services/reconciliation.py:379-399` | Differently. List by sandbox metadata; the guard runs through `attach` and `execute` (decision 8). |
| Docker socket for the API | `docker/docker-compose.syntropic137.yaml:180-245` | Not needed. The E2B executor talks to the E2B API. |

## 2. E2B facts

Every row below was fetched for this doc. Sources:

- [e2b.dev/pricing](https://e2b.dev/pricing), accessed 2026-10-08
- [docs: billing and limits](https://e2b.dev/docs/billing), accessed 2026-10-08
- [docs: persistence](https://e2b.dev/docs/sandbox/persistence), accessed 2026-10-08
- [docs: internet access](https://e2b.dev/docs/sandbox/internet-access), accessed 2026-10-08
- [docs: background commands](https://e2b.dev/docs/commands/background), accessed 2026-10-08
- [docs: template base image](https://e2b.dev/docs/template/base-image), accessed 2026-10-08
- [docs: secrets](https://e2b.dev/docs/secrets), accessed 2026-10-08
- [llms.txt](https://e2b.dev/llms.txt), accessed 2026-10-08

| Item | Value | Source (accessed 2026-10-08) |
|---|---|---|
| Plans | Hobby $0 (one-time $100 credit), Pro $150/mo, Enterprise custom ($3,000/mo minimum) | [pricing](https://e2b.dev/pricing), accessed 2026-10-08 |
| Concurrency | Hobby 20; Pro 100 included; Pro+ 600 for +$500/mo; Pro++ 1,100 for +$1,000/mo | [pricing](https://e2b.dev/pricing), accessed 2026-10-08 |
| Limits | 8 vCPU, 8 GiB; disk 10 GiB (Hobby), 20 GiB (Pro); continuous runtime 1 h (Hobby), 24 h (Pro); creation 1/s (Hobby), 5/s (Pro) | [billing](https://e2b.dev/docs/billing), accessed 2026-10-08 |
| Rates | vCPU $0.000014/s each; memory $0.0000045/GiB/s; storage free at plan size | [pricing](https://e2b.dev/pricing), accessed 2026-10-08 |
| Default RAM | **Unresolved.** The pricing table marks 4 GiB as default; the billing FAQ and the template page say 2 vCPU and 512 MiB | [pricing](https://e2b.dev/pricing), [billing](https://e2b.dev/docs/billing), [base image](https://e2b.dev/docs/template/base-image), accessed 2026-10-08 |
| Egress | On by default; `allow_internet_access=False`; `allow_out` and `deny_out` lists of IPs, CIDRs or domains; domain filtering requires deny-all | [internet access](https://e2b.dev/docs/sandbox/internet-access), accessed 2026-10-08 |
| Pause and resume | Pause takes about 4 s per GiB of RAM, resume about 1 s. A pause can be refused with HTTP 503 (`ServiceBusyException`) while a previous snapshot is finishing; the sandbox keeps running | [persistence](https://e2b.dev/docs/sandbox/persistence), accessed 2026-10-08 |
| Paused-sandbox storage cost | **None published.** "You only pay while a sandbox is actively running. Once a sandbox is paused, killed or times out, billing stops immediately." Paused retention is unlimited, with no TTL | [billing](https://e2b.dev/docs/billing), [persistence](https://e2b.dev/docs/sandbox/persistence), accessed 2026-10-08 |
| Spending limit | Available on the budget page | [billing](https://e2b.dev/docs/billing), accessed 2026-10-08 |
| Reattach to a running command | `Sandbox.connect(sandbox_id)` then `sandbox.commands.connect(pid)` from a separate process | [background commands](https://e2b.dev/docs/commands/background), accessed 2026-10-08 |
| Templates from an image | `template.from_image("...")`; a "Private registries" page exists but was not read, so digest pinning from private GHCR is **not verified** | [base image](https://e2b.dev/docs/template/base-image) |
| Secret injection | Stored secrets referenced from a network rule; the egress proxy injects the value into matching outbound HTTPS requests outside the sandbox. Per-host request transforms are public beta | [secrets](https://e2b.dev/docs/secrets), [internet access](https://e2b.dev/docs/sandbox/internet-access), accessed 2026-10-08 |
| BYOC | Enterprise only: sandboxes in our own AWS, GCP or Azure account and VPC, operated by E2B | [llms.txt](https://e2b.dev/llms.txt), accessed 2026-10-08 |
| Regions | **Not verified**: no region list was found in the pages read | |

Two points stated outright:

- **Pro is the floor.** Hobby's 1 h continuous-runtime cap equals the 3600 s
  phase timeout at `workflows/evals/verify-pinned-sonnet/workflow.yaml:43`.
- **The default-RAM inconsistency is reported, not resolved.** Templates set
  their own CPU and memory, so the template build in issue E pins both.

The secret-injection feature is relevant to decision 6 and #1735: it is a
vendor-run version of the broker we would otherwise build. Using it means E2B
holds the upstream credential. That is still a residency decision for the
owner (section 8, item 2), so this doc does not assume it.

## 3. Alternatives and recommendation

Marginal price is for one run at 2 vCPU and 4 GiB for one hour, computed from
the published per-second rates. "Not verified" means the pages read did not
state it; the comparison does not rank on those cells.

| | E2B | Modal Sandboxes | Daytona | Fly Machines | Self-hosted Firecracker or Kata on Hetzner AX | More Docker hosts as ADR-072 Executors |
|---|---|---|---|---|---|---|
| Isolation boundary | Firecracker microVM ([llms.txt](https://e2b.dev/llms.txt), accessed 2026-10-08) | gVisor, or `runtime="vm"` ([Modal sandboxes](https://modal.com/docs/guide/sandboxes), accessed 2026-10-08) | not verified | not verified | microVM we operate | container, today's hardening |
| Max concurrency | 100, 600, 1,100 by add-on; Enterprise more | 100 containers (Starter), 5,000 (Team); a sandbox-specific cap not verified ([Modal pricing](https://modal.com/pricing), accessed 2026-10-08) | not verified | not verified | what we buy | what we buy |
| Max lifetime | 24 h continuous on Pro | 5 min default, up to 24 h ([Modal sandboxes](https://modal.com/docs/guide/sandboxes), accessed 2026-10-08) | not verified | not verified | unbounded | unbounded |
| Custom image | template from image | yes, `modal.Image` ([Modal sandboxes](https://modal.com/docs/guide/sandboxes), accessed 2026-10-08) | not verified | not verified | yes | yes, today's images unchanged |
| Egress control | allow and deny lists | `block_network`, CIDR allowlist, domain allowlist on port 443 ([Modal sandbox networking](https://modal.com/docs/guide/sandbox-networking), accessed 2026-10-08) | not verified | not verified | ours to build | ours; open today (C1, #1794) |
| Marginal price, 2 vCPU / 4 GiB / h | 2 x $0.000014 + 4 x $0.0000045 = $0.000046/s = **$0.166/h** ([pricing](https://e2b.dev/pricing), accessed 2026-10-08) | 1 physical core (2 vCPU) x $0.00003942 + 4 x $0.00000667 = $0.0000661/s = **$0.238/h** (sandbox rates, [Modal pricing](https://modal.com/pricing), accessed 2026-10-08) | 2 x $0.0504 + 4 x $0.0162 = **$0.166/h**, plus $0.000108/GiB/h storage above 5 GiB ([Daytona pricing](https://www.daytona.io/pricing), accessed 2026-10-08) | performance-2x, 4 GB: $66.00/mo always-on = **$0.090/h** in iad ([Fly pricing](https://fly.io/docs/about/pricing/), accessed 2026-10-08) | not verified (the AX matrix renders prices client-side; [Hetzner AX](https://www.hetzner.com/dedicated-rootserver/matrix-ax/), accessed 2026-10-08) | 0 marginal; the host is a fixed cost |
| Fixed monthly cost | $150 Pro; +$500 or +$1,000 for 600 or 1,100 | $0 Starter, $250 Team | none stated on the pricing page | none stated | the server price, operator to supply | the server price, operator to supply |
| Retained-storage cost | none while paused, per [billing](https://e2b.dev/docs/billing) | not verified | $0.000108/GiB/h above 5 GiB | $0.15/GB/mo of rootfs while stopped | own disk | own disk |
| Credential story | none until #1735; vendor secret injection exists | none until #1735 | none until #1735 | none until #1735 | ours, but off the API host: still #1735 | unchanged: Envoy, setup secrets, today's posture |
| Fit with ADR-072 | one remote Executor per account | one remote Executor | one remote Executor | one remote Executor, or Fly as a host for more Executors | more local Executors on hosts we own, plus a microVM provider | more local Executors (#1734) |

### Cost is a formula, not a verdict

```
cost per run-hour = fixed_monthly / (730 x utilization x concurrent_runs)
                  + marginal_rate x sizing
                  + retained_storage
```

Utilization and per-run sizing are **inputs to measure**, by #1716 and by the
teardown resource usage PR #1608 records. This doc does not state them.

Runs per host is not a denominator anyone has measured.
`docs/north-star.md:142` warns that the per-run CPU figure is a hypothesis
(load average does not measure it). The table below is a **scenario**, so the
reader sees how the answer moves. `V` is the owned host's monthly price,
operator to supply. Utilization is held at 1 to isolate the effect of
packing.

| Scenario: runs per owned host | Owned host cost per run-hour | E2B Pro fixed share at 100 concurrent, utilization 1 | E2B marginal per run-hour (2 vCPU / 4 GiB) |
|---|---|---|---|
| 4 | V / 2,920 | $150 / 73,000 = $0.0021 | $0.166 |
| 6 | V / 4,380 | $0.0021 | $0.166 |
| 10 | V / 7,300 | $0.0021 | $0.166 |
| 16 | V / 11,680 | $0.0021 | $0.166 |

At lower utilization the fixed shares grow as 1 / utilization on both sides;
the E2B marginal rate does not. An owned host is cheaper per run-hour than E2B
when `V / (730 x utilization x runs_per_host) < $0.166`. Whether that holds is
exactly what #1716 has to measure.

### Recommendation (conditional on #1716 and the unverified vendor cells)

- **At 100:** more owned Docker hosts, as additional ADR-072 Executors (#1734),
  are the base, because the credential posture is unchanged. E2B is the burst
  tier, and only after #1735. Before #1735 E2B carries only scripted runs, so
  it adds nothing for real work at 100.
- **At 1,000:** an owned fleet sized for steady load, plus a remote burst
  tier. The choice between E2B Pro++, Enterprise and self-hosted Firecracker
  depends on the measured burst share. Model-provider quota
  ([#1718](https://github.com/syntropic137/syntropic137/issues/1718)) is
  hypothesised to bind first (`docs/north-star.md:173`, `docs/north-star.md:184`).

## 4. Adapter design

Nine decisions. Each names the rejected option inline.

### Decision 1. A remote backend is an Executor, not a router

An E2B tier is one ADR-072 Executor process: role `executor`, the same image
(ADR-072 D1), configured with `backend = e2b`. It registers one
`execution_budget` row with `backend = 'e2b'`, capacity seeded at or below the
plan's concurrency cap (ADR-072 D3). It claims, leases, heartbeats and drains
like a local Executor (D3, D4, D10). One Executor drives exactly one backend,
so no code path branches on backend per run.

*Rejected:* one process driving both backends. It couples E2B API latency to
the local runs' loop and puts a backend branch in every call.

### Decision 2. Placement is the claim predicate

"Remote claims only when no local slot is free" (#1612) becomes one extra
condition in ADR-072 D3 step 1, applied only on rows whose backend is remote:
`NOT EXISTS (a live, non-draining local row with in_use < capacity)`. It lives
in the one `ExecutionRunQueue.claim` implementation.

- **Accepted race:** a local slot freed just after a remote claim does not
  pull the run back. There is no preemption and no migration (ADR-072 D5).
- **Disabling claims:** an outage breaker or operator action **disables new
  claims** on the row, using the D10 draining state (a draining host gets no
  claim, `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:168-169`),
  or a `claims_enabled` flag if D10's drain does not fit. It never sets
  `capacity = 0`: `CHECK (in_use >= 0 AND in_use <= capacity)` (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:154`) would
  reject that write while any run is charged. Accounting is untouched; charged
  runs finish or are fenced normally.

*Rejected:* an admission-time router (ADR-021 `WorkspaceRouter`). It counts
capacity outside the claim transaction, which D3 forbids ("A count taken
outside the claim transaction is racy and is not acceptable", `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:177-179`).

### Decision 3. One composition point per backend: the BackendKit

This keeps #1612 Step 7a's single composition point and names it the
**BackendKit**: one object per backend, built once at Executor wiring. It owns
every backend-specific decision, so no caller coordinates vendor choices:

- **provider:** create, execute, files, stream, ownership;
- **image resolver:** Docker verifies the cosign signature and returns a
  digest; E2B returns a template id with a recorded source digest that was
  verified at build time;
- **capture strategy:** a Docker volume mount, or the E2B spool directory
  plus pause retention;
- **credential policy:** decision 5;
- **recovery access:** decision 8;
- **isolation type:** the reported value.

Today these decisions are unconditional inside the Docker adapter: capture
mounts at
`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:295-299`,
verification at `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:321`, and `isolation_type="docker"` at `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:370`. They move into
the Docker kit unchanged.

Code location, by the CLAUDE.md boundary test:

- **agentic-workspace:** `E2BWorkspaceProvider` and the capability Protocols of
  decision 4, beside `SupportsWorkspaceLogs`
  (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/base.py:237-238`)
  and `SupportsStagedTeardown` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/base.py:284-285`). They are transport knowledge that
  changes when E2B ships a new SDK.
- **syn137:** the BackendKit, the credential policy, the budget row, the claim
  predicate, pricing, the `IsolationBackendType` value and the reconciler.
  These are domain meaning.

*Rejected:* calling the E2B SDK directly from syn-adapters. It puts vendor
transport outside the submodule, where it drifts silently.

### Decision 4. Capability Protocols that carry today's full behaviour

Each is defined in agentic-workspace, and the Docker provider implements it
first.

**`SupportsStreamingExec`**, keeping #1612 Step 7's session and outcome
contract. `start(workspace, sandbox_argv, *, cwd, env, timeout) -> StreamSession`.
The session offers:

- `lines()`: stdout and stderr **merged**, matching `stderr=STDOUT` at
  `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:180`;
- `outcome() -> StreamOutcome`, carrying `exit_code`, `timed_out`, `signal`,
  and `disconnected` (the stream was lost, but the process may live) as
  distinct from `completed`;
- `cancel()`, which stops the **sandbox** process, not just the local pipe;
- `reconnect()`, which reattaches to the same process (E2B
  `commands.connect(pid)`, verified in section 2).

Per-command env goes in `env`, never baked into the argv.

**Transport argv and sandbox argv are separated.** syn137 builds the sandbox
argv, `sh -c <announce-then-exec> <wrapper> <announce> <command...>`
(`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_helpers.py:71-72`),
so launch evidence (#1065) keeps one shape. Only the Docker provider prepends
`docker exec -i -w ... -e ... <container>` (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_helpers.py:66-70`).

Signal-death capture
(`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:206`,
which takes the docker argv today) and lost-status diagnosis
(`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:546-552`)
become provider methods. A provider that cannot diagnose returns an explicit
"no diagnosis", never a fabricated one.

**`SupportsFileTransfer`.** `read_files(workspace, patterns, *, base_path) -> list[tuple[str, bytes]]`.
It is binary-safe and pattern-aware. `base_path` is absolute: `/workspace`,
`/spool` or `/opt/agentic`. Returned paths are relative to `base_path`. The
existing `read_file` keeps its documented relative-path, text contract
(`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/base.py:201-218`),
so no existing caller changes meaning. The Docker implementation keeps its
host-path fast path when a host path exists. Consumers route through it:
artifact `copy_from`
(`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:582-583`)
and the manifest read
(`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:163-172`,
which stops reaching into `_active_workspaces`).

**`SupportsOwnership`.** `list_owned(labels) -> list[OwnedWorkspace]` and
`attach(workspace_id, *, expect_labels) -> Workspace`. **`attach` refuses** a
workspace whose `syn.host_id` or `syn.execution_id` metadata does not match
(#1612 Step 8). `_workspaces`
(`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:230`)
becomes a cache that `attach` fills on a miss.

### Decision 5. A credential-free mode, enforced by the executor

A Scripted Agent runs under `provider: claude` or `codex`, and production
accepts no third value
(`packages/syn-shared/src/syn_shared/agents.py:253-269`). So nothing about the
workflow can say "this needs no credential" (C7). The guarantee therefore
lives where credentials are produced.

- **One port, `WorkspaceCredentialPolicy`** (orchestration context), consulted
  by **every** credential source:
  - the `with_sidecar` and `inject_tokens` arguments to `create_workspace`
    (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:434-441`);
  - `SetupPhaseSecrets.create`, for GitHub and Codex auth (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:523-531`);
  - `_build_agent_env`, for Claude (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:216-271`, called at `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:760`);
  - the session-store write token
    (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:237-257`).

  Two implementations. `HostCredentials` is today's behaviour, unchanged.
  `NoCredentials` supplies nothing at every source, requests no sidecar and no
  token injection, and **refuses before `create_workspace`** any phase with a
  non-empty repo list, because `clone_repos: false` still hands repos to setup
  secrets (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:512-516`). The BackendKit supplies the policy, so it is fixed per
  executor at wiring, never chosen per run.
- **The image is tied to the mode.** A `NoCredentials` kit refuses to start
  unless its template's recorded source digest is the pinned stub image digest
  (from `PINNED_DIGESTS`), and refuses any per-run `config.image` that
  differs. An ordinary Claude image cannot run under the mode, and if it could,
  there would be nothing to authenticate with.
- **Run identity reaches admission and survives restart.** The start request
  carries an optional `ScriptedAgentProfile`, already a frozen,
  `extra="forbid"` Pydantic contract
  (`packages/syn-perf/src/syn_perf/loadtest/scripted_agent_profile.py:109-113`)
  that nothing in production passes today (`packages/syn-perf/src/syn_perf/loadtest/scripted_agent_profile.py:37-38`). The profile is recorded
  as an optional field on the execution-start event (default `None`, for
  replay), so it is domain truth after a restart. It is copied to an
  `execution_runs.workload` column (`scripted` or `agent`) at reserve, for the
  claim predicate. Provisioning injects it as `SYN_SCRIPTED_AGENT_PROFILE`.
  Where the contract module lives is left to issue H: it may move from
  syn-perf to syn-domain so the event can type it, because dependency
  direction forbids syn-domain importing syn-perf.
- **The claim predicate gains one clause** for an executor whose policy is
  `NoCredentials`: `workload = 'scripted'`. The two layers are independent:
  the claim never hands such an executor a real run, and if it did, there is
  nothing to inject.

*Rejected:* detecting credential freedom from the workflow, or checking just
before `_build_agent_env`. No workflow field can say it, and that check misses
setup secrets, the sidecar and the session-store token.

### Decision 6. Credentials after #1735

The sandbox holds only a per-run, short-lived capability. A broker on our side
exchanges it for upstream auth, reached through an authenticated public
ingress, because Envoy on `agent-net` is not reachable. E2B egress is deny-all
plus an allowlist: the broker, github.com and the package registries.

OAuth (Claude Max) runs stay local-only unless the owner decides otherwise,
because header substitution of OAuth is out of scope
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:251`).
This becomes a third `WorkspaceCredentialPolicy` implementation,
`BrokeredCredentials`. No other code changes shape.

*Rejected:* "option A", raw credentials in the sandbox with egress restricted.
That is a residency and trust decision for the owner (`docs/north-star.md:182`).
E2B's vendor-side secret injection (section 2) is a variant of the same
decision: the credential leaves our hosts, though not into the sandbox.

### Decision 7. Telemetry and capture: keep #1612 Step 8

- **Lane 2 is unchanged.** The E2B stream feeds the same stream processors.
  Vendor cost (sandbox seconds x rate) is a Lane 2 observation and never an
  aggregate input.
- **Teardown ordering.** The E2B provider implements `SupportsStagedTeardown`
  (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/base.py:284-324`),
  mapping the hooks to its storage model, where the "workspace directory" is
  the sandbox's own disk:
  1. `while_running`: the host invokes the exporter and reads its exit status.
  2. Live drain: transcripts and the child journal are read through the
     **existing** execute-based readers, `WorkspaceSpoolReader` and
     `WorkspaceChildJournalReader`
     (`packages/syn-adapters/src/syn_adapters/session_inventory/docker_recovery.py:121-141`),
     each given the provider's `execute`.
  3. `before_delete`: archive and confirm durability.
  4. Kill **only after a complete, exclusive drain.**

  If the drain is incomplete or the archive upload fails, the sandbox is
  **paused, not killed** (pause-until-drained) and left to the recovery
  worker. This is the order the Docker contract already enforces; "delete"
  means "kill the sandbox". A pause can be refused with 503 (section 2), so the
  provider retries the pause and, while it is refused, the sandbox stays
  running and is still never killed.
- **Durable routing.** `CaptureSpool`
  (`packages/syn-domain/src/syn_domain/contexts/agent_sessions/ports/SessionCaptureSpoolPort.py:14-18`)
  gains optional fields `backend`, `executor_id` and `sandbox_id`, defaulting
  to the Docker values for existing rows, and a profile value for the remote
  spool. A fresh worker finds the sandbox from the row, not from memory.
- **Runtime wiring.**
  `packages/syn-adapters/src/syn_adapters/session_inventory/runtime.py:183`
  stops hard-wiring `DockerSpoolRecovery` and selects a `SpoolRecoveryPort`
  (`packages/syn-adapters/src/syn_adapters/session_inventory/recovery_worker.py:45-48`)
  per spool backend. A worker claims only spools whose backend it holds
  recovery access to (decision 8).
- **Exclusive drain**, for a sandbox: the run's agent session has a known
  outcome, or the run is `fencing`, `reaped` or closed, and the worker holds
  the spool lease. The `CaptureRecoveryWorker`
  (`packages/syn-adapters/src/syn_adapters/session_inventory/recovery_worker.py:85-116`)
  is reused unchanged: it resumes the paused sandbox, drains, marks drained,
  and only then releases. For E2B, release means killing the sandbox.
- **Retention limits.** The existing age and bytes limits
  (`packages/syn-adapters/src/syn_adapters/session_inventory/runtime.py:184-192`)
  apply per backend, plus a paused-sandbox count ceiling. E2B publishes no
  charge for paused sandboxes and keeps them indefinitely (section 2), so the
  ceiling bounds accumulation, not spend; a cost ceiling is kept as a guard
  against a pricing change.

*Rejected:* read-at-teardown capture with live-only recovery. It loses the
spool on any crash.

### Decision 8. Recovery access is separate from provisioning

ADR-072 D5 lets any live executor fence an expired run, and the reap must
report complete before `reaped`
(`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:268`,
`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:276`). A Docker executor cannot list E2B sandboxes. A finite sandbox timeout
bounds money, not correctness: an unknown cleanup leaves `fully_reaped` false
(`apps/syn-api/src/syn_api/services/reconciliation.py:336-341`).

- **The registry records each executor's backend and account reference** (an
  identifier, not a secret) on its durable row. The fencer resolves the dead
  owner's backend from that row.
- **Recovery kit.** A narrow capability that can list, attach (with ownership
  checks), execute, read files and kill on one backend and account. It is
  configured on whichever executors should cover that backend. Its E2B API key
  is a cleanup credential held on our side, never inside a sandbox.
- **Proposed ADR-072 D5 amendment (C8).** The `claimed -> fencing` guard adds
  `backend IN <backends this executor can recover>`. An executor without the
  kit never fences an E2B run, so a run is never stranded in `fencing` under a
  reconciler that cannot reap it. Takeover keeps the same rule. A failed list
  or kill leaves the run in `fencing` with its charge held (ADR-072 D3,
  `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:212-213`).
- **The unpushed-work guard** (#1560;
  `apps/syn-api/src/syn_api/services/reconciliation.py:355-357`, `apps/syn-api/src/syn_api/services/reconciliation.py:379-399`)
  runs inside a remote orphan through the kit's `attach` and `execute` before
  the kill. Scripted runs push nothing, but after #1735 real runs will.

### Decision 9. ADR-060

Any E2B fake inherits `InMemoryAdapter`
(`packages/syn-adapters/src/syn_adapters/in_memory.py`). Production wiring
fails fast if `backend = e2b` and no E2B key or template is configured. It
never falls back to Docker.

### Failure modes

| Failure | Detection | Handling |
|---|---|---|
| Sandbox dies mid-phase | `outcome()` reports completion with no result, or an E2B "not found" | The phase fails as a container death does today; no auto-retry (ADR-072 D5). The spool is gone with the disk; that capture loss is reported by backend. |
| Network split, Executor alive | `outcome().disconnected` | `reconnect()` within a bounded window. If that fails: `attach` with ownership check, then `cancel`, then fail the phase. The lease keeps renewing, so this is the Executor's own timeout, not fencing. |
| Executor dies | Lease expiry (ADR-072 D4, 90 s) | An executor holding the E2B recovery kit fences and reaps by `syn.host_id` metadata (decision 8). A failed reap stays in `fencing`. A sandbox timeout of the phase deadline plus margin bounds spend only. |
| Quota or concurrency refused at create | E2B error on create | `defer` with `retry_at`, which releases the slot (ADR-072 D3). |
| E2B outage | Creates fail; heartbeat continues | A breaker **disables claims** on the E2B row after K consecutive create failures; capacity is untouched (decision 2). Local rows never wait on it. |
| Archive upload fails at teardown | `before_delete` raises | The sandbox is paused, not killed; the recovery worker retries (decision 7). |
| Pause refused | HTTP 503 / `ServiceBusyException` | Retry the pause; the sandbox keeps running and is never killed before a complete drain. |
| Paused sandboxes accumulate | Paused count above ceiling | Alert. Retention limits apply. A sandbox is never killed before a complete drain unless the operator overrides. |
| Spend runaway | E2B spending limit; Lane 2 cost observation | Set the limit and alert. |

## 5. Phased build plan and the issues to file

None of these is filed by this PR (section 8, item 1). Each is written so it
can be filed as is.

### A. Provider capability Protocols: streaming session, file transfer, ownership (agentic-workspace)

- **Context:** decision 4. Today the stream, files and lookup are Docker-only.
- **Change:** the three Protocols; Docker implementations; a conformance suite
  parametrised over providers. Library code delivered by a pin bump, no image
  rebuild.
- **Acceptance:**
  - a conformance test runs a command writing to both stdout and stderr and
    asserts the merged order, the exit code, and the `timed_out` and
    `disconnected` distinctions;
  - `read_files` round-trips a binary file under `/workspace` and `/spool`;
  - `list_owned` returns exactly the workspaces with a given `syn.host_id`;
  - `attach` with mismatched labels raises.
- **Negative control:** a Docker `read_files` that decodes to text fails the
  binary round-trip.
- **Depends on:** nothing.

### B. Route the agent stream and workspace lookup through the provider (syn137)

- **Context:** decision 4; the stream is a local `docker exec`
  (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_helpers.py:66`).
- **Change:**
  `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:159-212`
  builds only the sandbox argv and calls `SupportsStreamingExec`; signal-death
  and lost-status diagnosis become provider calls; the `_workspaces` cache is
  filled by `attach`; `isolation_type` comes from the kit.
- **Acceptance:** a test through the **production** `AgenticEventStreamAdapter.stream` (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:69`, `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:106`)
  and the engine, with a provider fake, asserts that the provider received the
  sandbox argv with no `docker` prefix, that `last_exit_code` reflects the
  fake's outcome, and that cancellation calls `cancel()`.
- **Negative control:** reverting B makes the adapter spawn `docker exec`, the
  fake receives nothing, and the test fails. This is unlike
  `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/test_stream_timeout_visibility.py:71-78`,
  which calls `read_lines` directly and would pass either way.
- **Depends on:** A.

### C. Route artifacts and the image manifest through provider file transfer (syn137)

- **Context:** C4; artifacts silently vanish without a host path.
- **Change:** `copy_from`
  (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:582-583`)
  and `_read_image_manifest`
  (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:150-172`)
  use `read_files`.
- **Acceptance:**
  - a handle with **no host path** returns artifacts (today it returns `[]`,
    `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter_copy.py:158-160`);
  - a binary artifact survives byte for byte;
  - a manifest whose `manifest_digest` differs from the kit's pinned digest is
    recorded as read and flagged, not dropped to `None`.
- **Negative control:** reverting C makes the no-host-path test return `[]`.
- **Depends on:** A.

### D. BackendKit composition point and WorkspaceCredentialPolicy (syn137)

- **Context:** decisions 3 and 5; #1612 Step 7a.
- **Change:** the BackendKit, with the Docker kit absorbing today's
  unconditional capture, verification and isolation type. The
  `WorkspaceCredentialPolicy` port with `HostCredentials` and `NoCredentials`,
  consulted at all four sources.
- **Acceptance:**
  - with **host credentials configured** (Claude token, API key, GitHub App,
    Codex auth, session-store token), a `NoCredentials` provision of a valid
    scripted phase shows no credential in setup secrets, in files written to
    the workspace, or in any command env, checked by scanning every recorded
    `execute`, `write_file` and stream `env`;
  - a phase with repos is refused before `create_workspace` is called;
  - a `NoCredentials` kit configured with the claude-cli digest refuses to
    start.
- **Negative control:** making `_build_agent_env` bypass the policy makes the
  env scan fail.
- **Depends on:** nothing. It is local behaviour, unchanged under
  `HostCredentials`.

### E. E2B provider and template from the pinned image, with an isolated smoke test (agentic-workspace)

- **Context:** validate the provider before any placement stack exists.
- **Change:** `E2BWorkspaceProvider`, implementing the base Protocol, A's
  capabilities and `SupportsStagedTeardown`; a template build from a pinned
  digest, recording the source digest and pinning CPU and RAM.
- **Acceptance**, the first remote proof, with no queue, no executor and no
  credentials: against a real E2B account, the A conformance suite passes
  (create, merged stream and outcome, binary file round-trip, list and attach,
  cleanup), and nothing is left in the E2B list afterwards. The same issue
  runs the Codex bwrap smoke test (Q4), the read-only root and private GHCR
  digest checks (Q5), and pause and resume of a sandbox with a spool
  directory, and writes the results back into this doc.
- **Negative control:** a provider whose `kill` is a no-op leaves a sandbox in
  the E2B list and fails the cleanup assertion.
- **Depends on:** A. Needs an E2B API key in CI or the operator's environment,
  which is a human decision.

### F. Capture spool routing and recovery for remote backends (syn137)

- **Context:** decision 7; #1612 Step 8.
- **Change:** `CaptureSpool` backend, executor and sandbox fields; per-backend
  `SpoolRecoveryPort` selection at
  `packages/syn-adapters/src/syn_adapters/session_inventory/runtime.py:183`;
  E2B recovery reusing the execute-based readers; pause-until-drained
  teardown; retention limits per backend.
- **Acceptance:**
  - a **fresh worker** (new process, empty memory) recovers a paused
    sandbox's spool from the durable row;
  - a failed archive upload leaves the sandbox paused and the spool
    retryable;
  - the child journal is recovered;
  - release (kill) happens only after `mark_drained`;
  - a worker without E2B access never claims an E2B spool.
- **Negative control:** wiring Docker recovery only makes the fresh-worker
  test fail.
- **Depends on:** A, E.

### G. E2B Executor: budget row, overflow predicate, claim disable, recovery kit (syn137)

- **Context:** decisions 1, 2 and 8.
- **Change:** those decisions, plus the ADR-072 D5 fence-guard amendment (C8)
  as an ADR edit inside this issue. The ubiquitous-language entries land here:
  Executor backend, Overflow, Placement, Recovery kit, Credential policy, with
  `Router` listed as a rejected word.
- **Acceptance:**
  - with one local row at `in_use < capacity`, the E2B Executor claims
    nothing;
  - with the local row full, it claims the oldest admitted row;
  - an `agent` workload row is never claimed by a `NoCredentials` E2B
    Executor;
  - the breaker disables claims while runs are charged, and the row's `CHECK`
    still holds;
  - a dead E2B Executor is reconciled by a local Executor holding the kit;
  - failed list or kill calls keep `fencing` and the charge;
  - a local Executor without the kit never fences the run.
- **Negative control:** removing the overflow clause makes the first claim
  test fail.
- **Depends on:** ADR-072 Phase 1 (#1310 items 1.2-1.7), #1734, B, C, D, E.

### H. First end-to-end remote run: Scripted Agent on a repo-free workflow (syn137 and agentic-workspace)

- **Context:** the brief proposed eval verify as the first slice. It is
  rejected because eval verify needs Claude and GitHub credentials (C5).
- **Change:** the start request carries `ScriptedAgentProfile`; the optional
  start-event field; the `execution_runs.workload` column;
  `SYN_SCRIPTED_AGENT_PROFILE` injection; the stub image (agentic-workspace
  step 7b) pinned and built as the E2B template; a fixture workflow with
  `requires_repos: false` and `clone_repos: false` on every phase, run at the
  node tier with no certified ending, so each phase's side effect is
  `ReportOnly`
  (`packages/syn-perf/src/syn_perf/loadtest/scripted_agent_profile.py:498-513`).
- **Acceptance:** one execution reaches `completed` with `isolation_type`
  reported as E2B, **output artifacts collected**, the transcript archived
  through the F path, the image manifest recorded, no credential observed
  (D's scan, on the live path), and no sandbox with its `syn.execution_id`
  left in the E2B list.
- **Negative control:** routing the run through a `HostCredentials` kit fails
  D's credential scan on the live path.
- **Depends on:** F, G, the stub image.

### I. Credentials for remote sandboxes via broker and egress allowlist (syn137)

- **Context:** decision 6.
- **Change:** `BrokeredCredentials`. After this, real Claude runs go to E2B and
  the `workload` clause is lifted for brokered executors.
- **Acceptance:** a brokered run completes with no upstream credential in the
  sandbox (D's scan), and a request to a host outside the allowlist fails.
- **Negative control:** dropping deny-all from the sandbox network config makes
  the off-allowlist request succeed and the test fail.
- **Depends on:** #1735, H.

### J. agent-net has open egress in production (syn137, security)

- **Already tracked as
  [#1794](https://github.com/syntropic137/syntropic137/issues/1794)**; listed
  here because it changes what "parity" means. Evidence: C1,
  `docker/docker-compose.syntropic137.yaml:674-676`,
  `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:219-221`.
  Acceptance and negative control belong to #1794.
- **Depends on:** nothing; independent of E2B.

**Build order:** A; then B, C, D and E in parallel; then F; then G; then H;
then I. J (#1794) at any time. E gives the first real remote signal without
the placement stack.

## 6. Rejected alternatives

- **An admission router** (ADR-021 `WorkspaceRouter`, overflow threshold): it
  decides placement outside the claim transaction (ADR-072 D3, `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:177-179`),
  and #1612 superseded it.
- **One Executor for both backends:** backend branches in every call, coupled
  failure domains.
- **Running the Executor inside the cloud or the sandbox:** moves every
  credential off-host.
- **"Option A", raw credentials in the sandbox:** an owner decision, not a
  default.
- **Eval verify as the first slice:** needs Claude and GitHub credentials (C5).
- **Detecting credential freedom from the workflow:** no workflow field can
  say it (C7), and a check just before `_build_agent_env` misses setup
  secrets, the sidecar and the session-store token.
- **A line-iterator stream Protocol:** cannot produce `last_exit_code`,
  timeout or disconnect outcomes.
- **Read-at-teardown capture with live-only recovery:** loses the spool on any
  crash, and silently departs from #1612 Step 8.
- **Setting capacity to 0 as an outage breaker:** violates the D3 `CHECK`
  while runs are charged.
- **Reusing `IsolationBackendType.CLOUD`:** attribution needs the vendor.
- **Leading with self-hosted Firecracker:** owning a VM fleet before any
  measured demand (#1716). The claim that OrbStack cannot run Firecracker on
  macOS is **not verified**.

## 7. Risks

| Risk | Signal |
|---|---|
| This doc drifts from ADR-072 by restating it | Claim, lease or fence mechanics written out here instead of cited by decision number. |
| A vendor fact goes stale | A section 2 or 3 cell with no URL and access date. |
| The overflow predicate starves remote or local work | An E2B row at `in_use = 0` with admitted rows older than one claim interval while every local row is full; or remote claims while a local row is free. |
| Remote capture loss | Sessions with `capture_session_id` and no archived transcript, by backend; paused-sandbox count rising. |
| Silent artifact loss | E2B phases with zero collected artifacts where the workflow expects output. C's no-host-path test is the guard. |
| The credential gate is bypassed | D's env, file and setup scan fails; any `NoCredentials` provision that reaches `SetupPhaseSecrets` with a repo. |
| A run stranded in `fencing` | A `fencing` row older than N lease periods whose reconciler lacks the backend kit (impossible after C8). |
| Leaked or paused sandboxes accumulate | The E2B list shows `syn.host_id` values with no live executor row; E2B spend above the Lane 2 estimate. |
| Codex cannot run on E2B | E's smoke test fails, and the remote tier is Claude-only. |
| Building G before ADR-072 Phase 1 | Any PR adding E2B to `WorkspaceService.create` while admission still uses `apps/syn-api/src/syn_api/execution_budget.py`. |

**Maintenance cost:** one provider in the submodule tracking the E2B SDK (pin
bump, no image build); three capability Protocols that every future provider
implements; one kit per backend; one credential-policy port with three
implementations; one spool-routing extension; one predicate clause; one
ADR-072 amendment.

## 8. Needs a human decision

None of these blocks this doc.

1. **Filing issues A to I** and linking them under #1612 (J is #1794). Filing is
   outward-facing; this doc carries the titles and bodies.
2. **Whether a raw credential may ever leave our hosts** before #1735, either
   into a sandbox ("option A") or into E2B's secret store. This doc assumes no.
3. **OAuth (Claude Max) runs on remote.** If remote is API-key only, overflow
   cost follows API billing.
4. **`IsolationBackendType.E2B` versus reusing `CLOUD`.** This doc recommends a
   new value.
5. **The owned-host monthly price `V`** for the cost formula.
6. **Whether to amend #1612's body** with C1 to C8, or only reference them from
   here.
7. **E2B plan tier, spending limit and an API key** for issue E, and where that
   key and the recovery-kit key are held.
8. **The ADR-072 D5 fence-guard amendment (C8).** It edits an Accepted ADR, so
   the owner should agree before issue G changes it.

## Open questions

- **Q4:** does Codex's bwrap sandbox work inside an E2B microVM? Settled by
  issue E.
- **Q5:** can a template be built from a private GHCR digest, and can the
  sandbox root be read-only with tmpfs mounts? Settled by issue E.
