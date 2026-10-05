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

## Where we are (measured, 2026-10-05)

From [the 2026-10-04 retrospective](retrospectives/2026-10-04-dogfood-orchestrator-day.md) and #1600:

- **Peak:** 9 concurrent executions on flywheel pushed load to 21 on 16 cores. One `/sessions` read took 55 s.
- **Control plane starved:** the API (HTTP, every projection, all orchestration) was capped at 0.5 CPU and Postgres at 1 CPU, while each workspace may use 2 CPUs. Raising both to 2 CPUs brought reads back to 0.3-0.8 s under the same load.
- **Resumes run one at a time,** and a queued start is invisible until it gets a slot (#1557).
- **Deploys need an idle platform:** a swap kills in-flight runs (#1310).
- **Transient failures fail whole runs:** a dropped GitHub connection or a model "at capacity" (#1593).
- **Phases spend most of their time on checks:** 65% of phase time in gates and waits (#1585).

## What each tier needs

**20 on one node:**
- control-plane CPU reserved, and admission that will not oversubscribe host cores (#1600);
- one concurrency budget with visible queued starts (#1557);
- retire the trigger dispatcher's separate cap. `max_concurrent_dispatches` still defaults to 1, citing #865, but #865 was fixed on 2026-09-22 (one `PhaseRuntime` per execution); the default and its comment are stale and fold into the single budget (#1574);
- cheaper in-workspace gates (#1585);
- retry on transient errors (#1593);
- a measured per-run resource profile, so the budget is set from data rather than guessed.

**100:**
- executors split from the API and claiming from a durable run queue, with generations that overlap, so an API or gateway deploy no longer waits for a drain (#1310 phases 1-2; a queue alone does not give this);
- capacity and claim in one transaction (#1310 phase 1; ADR-072 is proposed, not yet written);
- per-host budgets;
- rate-limit-aware dispatch for model providers and GitHub;
- event ingestion and projections sized for the event rate at 100 runs.

The capacity plan (exec-ada7853eb9b3, posted on #1310) concludes that 100 on one 16-core node is not reachable by configuration: it would need about 8x less CPU and 4x less disk per running execution. 100 therefore means more nodes, or much cheaper runs. Host budgets and event rates for 100 come from that plan's measurements once they exist.

**1,000:**
- many executor hosts or cloud sandboxes through `IsolationBackendPort`;
- multi-host scheduling and fencing (#1310 phase 2);
- read models and the event store load-tested at 10x the 100-run event rate;
- cost and quota controls per tenant.

## How to use this

- **Before a design or a review:** ask "does this still work at 100 concurrent? At 1,000?" If not, say what breaks and file it.
- **Measure before you size.** Record the observed figure and its source, as above.
- **A concurrency limit that is a hard-coded constant is a defect.** It belongs in settings, sized from measurement.
- **When a run fails under load,** the paper cut names the tier it blocks.
