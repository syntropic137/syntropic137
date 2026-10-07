# North star: concurrent agents at scale

Syntropic137 exists to run many AI agents at once, safely and observably, so
that software can be built by fleets of agents rather than one at a time.
Concurrency is the product. Every design decision is judged against it.

## The targets

| Tier | Concurrent executions | Status | Where it runs |
|---|---|---|---|
| **Now** | **20** | not yet met; 9 saturated the host on 2026-10-05 | one self-hosted node (flywheel: 16 cores, 62 GB) |
| **Next** | **100** | the near-term goal, as soon as possible | one large node or a few nodes, executors split from the API |
| **Production** | **1,000** | the bar for "production ready" | many nodes and/or cloud sandboxes (Firecracker/E2B) behind `IsolationBackendPort` |

"Concurrent" is checked by a load run:
- **Workload:** `sdlc-implement-v3`-shaped executions, all admitted within 5 minutes, each with an agent actively working in a phase. A phase waiting in a queue does not count, and neither does a slot that is idle.
- **Duration:** sustained for at least 30 minutes.
- **The pass bar:**
  - p95 of the dashboard list and detail reads under 500 ms during the run;
  - zero executions lost or orphaned by load, or by a deploy made during the run;
  - every event the agents produced reconciled as captured (the #1550 detector reports no dropped starts, and the per-run event counts match the recorded transcripts).
- **Model tokens:** a recorded-playback or stub agent may stand in for the model, so the check can run on every beta.

A number reached by queueing everything, or by letting the control plane fall over, does not count.

Long-range sizing for 10k agents is in [scaling-to-10k.md](scaling-to-10k.md). It predates the measurements below; treat its numbers as estimates.

## Where we are (observed, 2026-10-05 to 2026-10-07)

From [the 2026-10-04 retrospective](retrospectives/2026-10-04-dogfood-orchestrator-day.md), #1600 and the operator:

- **Peak:** 9 concurrent executions on flywheel pushed load to 21 on 16 cores. One `/sessions` read took 55 s (2026-10-05).
- **Today's baseline** (operator report, 2026-10-07; not re-measured by the capacity-model phase): 5 workspaces, load 17 on 16 cores, 10 of 62 GB RAM in use, `SYN_WORKSPACE_CPU_LIMIT=2` and an 8 GB memory override. The code default for memory is 4096 MB (`packages/syn-shared/src/syn_shared/settings/workspace.py:39`).
- **Fixed since the 2026-10-05 snapshot:**
  - the control plane is no longer capped at 0.5 CPU: API and Postgres default to 2 CPU with a 4x CPU weight (#1602; `packages/syn-shared/src/syn_shared/settings/infra.py:183-221`);
  - one admission budget covers starts, resumes and triggers, and a queued start is visible (#1557, #1574);
  - workspace limits are applied at the adapter (#1606);
  - preflight fails fast (#1585);
  - deploy drain is bounded (#1699);
  - pausing no longer waits on queued resumes (#1617).
- **Still open:**
  - a deploy kills in-flight runs (#1310);
  - a graceful shutdown skips work preservation (#1381);
  - transient errors fail whole runs (#1593);
  - the API is OOM-killed at its 512 MB default (#1552);
  - a deployed event store can lag the ESP pin (#1708).

## Capacity model

**Scope of every figure here.** The workload is `sdlc-implement-v3`-shaped executions on flywheel (16 cores, 62 GB). The per-run figures come from the capacity plan on #1310 (exec-ada7853eb9b3, 2026-10-05), which labels each one as an estimate or one sample. **None of them is a measured distribution yet.**

The capacity-model phase on 2026-10-07 could reach no deployment (no API URL, no Docker). Three sets of figures are therefore **unmeasured**, not zero:
- p50/p90 tokens and cost per phase type and model, from `/api/v1/executions`;
- quota as % per run;
- `Workspace resource usage` samples, which are written to logs only (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:340-360`).

Filling them is #1716. Until then, size from the estimates and say so.

### Per-run inputs

| Input | Value | Status |
|---|---|---|
| Phase deadlines summed | 14,400 s per run (premise 1200, implement 3600, verify 3600, fix 3600, reverify 1800, finalize 600) | read from `workflows/sdlc/implement-v3/workflow.yaml` |
| CPU demand of an active run | about 1.2 CPU: 1.5-2.2 CPU while gating x about 0.65 gate duty | **estimate** (#1600, #1585) |
| Workspace CPU cap | 2.0 per workspace | `packages/syn-shared/src/syn_shared/settings/workspace.py:42` |
| Workspace RAM | 0.5-1 GB used; 4096 MB cap by default, 8 GB on the VPS | used: **estimate**; cap: `workspace.py:39` |
| Workspace disk | 1-3 GB per phase (clone, deps, caches; five of six phases start cold) | **estimate** |
| API memory per execution | at most about 55 MB (443 MB / 8 at OOM, baseline included) | **estimate**, upper bound (#1552) |
| Model requests per Claude agent | 0.03-0.1 req/s | **estimate** |
| GitHub requests per run (platform side) | about 6 token mints (one per workspace setup), plus up to 120 req/h per open PR head while check-run polling is active | read from code (#1719); agent-side calls **unmeasured** |
| Tokens and cost per phase and model | - | **unmeasured** (#1716) |
| Quota per run, Claude Max weekly and session | - | **unmeasured**. The orchestrator observed about 68% of the weekly limit left after a heavy day (2026-10-07) |
| Quota per run, Codex weekly | - | **unmeasured**. 2 capacity failures at a peak of 7 or fewer (retrospective) |

### Platform limits

| Limit | Value | Source |
|---|---|---|
| Execution budget | 4 by default, a constant | `packages/syn-shared/src/syn_shared/settings/execution.py:23` |
| API process | one uvicorn process, stdlib event loop, no `--workers` | `infra/docker/images/syn-api/Dockerfile:135,182` |
| API container | 2 CPU, 512 MB | `packages/syn-shared/src/syn_shared/settings/infra.py:183-184` |
| Postgres (event store tables, projections, observations) | 2 CPU, 1 GB, one instance | `infra.py:201-209` |
| Event store process | 512 MB | `infra.py:211` (OOM on replay: #1553) |
| Envoy model-proxy bucket | 100 burst, 10 req/s refill, global | `docker/sidecar-proxy/envoy.yaml:156-158` |
| Trigger dispatch guards | 50 per hour, and 10 per 60 s | `packages/syn-shared/src/syn_shared/settings/polling.py:86-107` |
| Check-run polling | one request per pending SHA every 30 s (webhooks stale) or 120 s (healthy); a SHA lives up to 2 h | `packages/syn-domain/src/syn_domain/contexts/github/services/check_run_ingestion.py:165-185`, `polling.py:60-82` |
| GitHub App | 5,000 req/h per installation | GitHub's documented limit. Not measurable from the workspace token (#1719) |
| Deploy | swaps the API and kills in-flight runs; drain is bounded at 45 min | #1310, #1699; `scripts/pit_stop.sh` |

### 20 concurrent, one node (flywheel)

| Resource | Need at 20 | Limit | Binds? |
|---|---|---|---|
| Host CPU | 20 x 1.2 = 24 CPU, plus 4 for the control plane | 16 cores | **yes: about 1.75x oversubscribed** (estimate). The first bottleneck |
| Admission | 20 slots | budget 4, a constant | yes, but by configuration: raising it today would admit into the CPU deficit (#1715) |
| API memory | 20 x 55 MB, about 1.1 GB | 512 MB | **yes** (#1552) |
| Host RAM | 10-20 GB for workspaces plus the platform | 62 GB; caps overcommit (20 x 4 GiB = 80 GiB, 20 x 8 GB on the VPS) | no, on use; the caps overcommit |
| Disk | 20-60 GB | not measured this phase. 63 GB free on 2026-10-05 (#1310 plan) | at risk |
| Codex, one account | 20 parallel verify/reverify phases at peak | 2 capacity failures at 7 or fewer | **likely** (hypothesis, #1718) |
| Claude Max, one token | 20 parallel agents | cap unknown | unknown (#1718) |
| Envoy bucket | 0.6-2 req/s | 10 req/s | no |
| GitHub installation | about 2,400 req/h if 20 PR heads poll every 30 s, plus mints and agent calls | 5,000 req/h | no, but it is half the budget before any agent call (hypothesis, #1719) |
| Trigger guard | 5-20 starts/h | 50/h | no |
| Transient failures | a dropped connection fails the run | - | yes, for reliability rather than capacity (#1593) |

**First bottleneck at 20: host CPU,** from cold gates. A higher budget only turns the deficit into deadline failures. The fix is cheaper runs (#1714) and a budget sized from measured demand (#1715), and both need the profile (#1716).

### 100 concurrent

| Resource | Need at 100 | Limit on flywheel | Binds? |
|---|---|---|---|
| Host CPU | 120 CPU, plus the platform | 16 | **7.5x.** One node would need about 8x less CPU per run. Not reachable by configuration |
| Disk | 100-300 GB | about 63 GB free | **yes** |
| Host RAM | 50-100 GB | 62 GB | **yes** |
| API process | about 5.5 GB, 100 `docker exec` streams, every projection, in one process | one process, 512 MB | **yes**: executors must split from the API (#1310) |
| Model providers | 100 parallel agents on one Claude and one Codex account | unknown caps | **likely the first external limit** (hypothesis, #1718) |
| Envoy bucket | 3-10 req/s | 10 req/s | **likely** (#1720) |
| GitHub installation | up to about 12,000 req/h if 100 PR heads poll every 30 s | 5,000 req/h | **yes, if check-run polling is active** (hypothesis, #1719) |
| Trigger guard | 25-100 starts/h | 50/h | **yes**, for trigger-driven starts (#1721) |
| Postgres and event store | 10-30 observation rows/s plus events (estimate) | one Postgres at 2 CPU / 1 GB | unknown; measure (#1722) |
| Deploys | runs survive a deploy | a deploy kills in-flight runs | **yes** (#1310, #1381) |

**First bottleneck at 100: host capacity** (CPU, disk and RAM all exceed one 16-core node). The decision is more nodes or about 8x cheaper runs. Behind that, the single API process. **The first external limit is hypothesised to be model-provider quota** (#1718), which no host purchase fixes.

### 1,000 concurrent

| Resource | Need at 1,000 | Limit | Binds? |
|---|---|---|---|
| Hosts | 1,200 CPU at today's demand, or about 150 at 8x cheaper runs | one node | **yes**: many executor hosts or cloud sandboxes through `IsolationBackendPort` (#1310 phase 2, #350) |
| Credentials off-host | remote sandboxes must not hold raw credentials | every credential is inside the sandbox today (#1612) | **yes**: gates the remote tier (#724) |
| Model providers | 1,000 parallel agents | per-account limits | **yes**: multiple accounts and per-tenant quota (#1718) |
| GitHub installation | up to 120,000 req/h from check-run polling alone | 5,000 req/h | **yes**, unless polling is batched (#1719) |
| Event store and projections | 10x the 100-run event rate | one Postgres | unknown, and there is no baseline rate yet (#1722) |
| Scheduling | placement, heartbeat, fencing across hosts | none | **yes** (#1310 phase 2) |

**First bottleneck at 1,000: there is no multi-host executor.** Every run is placed on one Docker host. Close behind are off-host credentials, and quota per account.

### Ordered path

Each step names the measurement that closes it, in its issue.

1. **Measure:** per-phase usage, tokens and cost served as p50/p95 (#1716), and the token-free load test (#1717). Every later number is sized from these.
2. **20, platform side:**
   - API memory sized for 20 (#1552);
   - transient-error retry (#1593);
   - shutdown preserves work (#1381);
   - deployed images match the pin (#1708).
3. **20, node side:**
   - cheaper gates through a warm read-only dependency seed (#1714);
   - then a budget sized from measured host capacity (#1715);
   - then prove N=20 with the node-tier load test (#1717).
4. **100:**
   - executors split from the API on a durable run queue, so deploys stop draining (#1310 phases 1-2);
   - per-provider budgets and quota telemetry (#1718);
   - GitHub call accounting and batched check-run polling (#1719);
   - a configurable Envoy bucket (#1720);
   - a trigger guard sized to throughput (#1721);
   - the host-spec decision: more nodes, or about 8x cheaper runs.
5. **1,000:**
   - the #724 credentials spike;
   - multi-host scheduling and fencing (#1310 phase 2);
   - the remote sandbox provider (#350);
   - event store and projections load-tested at 10x the 100-run rate (#1722);
   - per-tenant cost and quota controls.

All bottleneck issues carry the `scale` label and sit under the epic #1612.

## How to use this

- **Before a design or a review:** ask "does this still work at 100 concurrent? At 1,000?" If not, say what breaks and file it.
- **Measure before you size.** Record the observed figure and its source, as above.
- **A concurrency limit that is a hard-coded constant is a defect.** It belongs in settings, sized from measurement.
- **When a run fails under load,** the paper cut names the tier it blocks.
