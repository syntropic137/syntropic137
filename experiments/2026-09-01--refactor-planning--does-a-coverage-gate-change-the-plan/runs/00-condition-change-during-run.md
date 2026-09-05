# Condition change during the run (recorded contemporaneously)

Captured while the six runs were still in flight, before any scoring. Recorded
here rather than by editing README or eval-pack, both of which are frozen from
the hypothesis commit `c1f0bfbe`.

## What happened

`sdlc-research-plan-v3` - the baseline arm's workflow - was REPAIRED on the
deployment while runs A1/A2/A3 were executing. A peer session (`syntropic137-f6`)
reinstalled it from repo source, restoring the `agent` block that its own
export/edit/reinstall cycle had stripped.

## Timeline, with sources

| Time (UTC) | Event | Source |
|---|---|---|
| 23:43:47-58 | A1,B1,A2,B2,A3,B3 start | `started_at` on each execution |
| 23:45:18 | `c9690b27` "implement and pr-review phases must declare Write too" | `git log origin/main --format=%cI` |
| after 23:45:18 | v3 reinstalled from repo source | peer report; reinstall requires the fixed source |
| ~23:52 | v3 observed with `cross-model-review provider='codex'` | `GET /api/v1/workflows/sdlc-research-plan-v3` |

Before the repair, v3 reported `provider=None` on all four phases. It now
reports `claude, claude, codex, claude`.

## Does this contaminate the A arm?

**Probably not, and the run itself settles it.**

`ExecuteWorkflowHandler.handle()` calls `_get_executable_phases(workflow)` ONCE
at execution start and hands the resulting list to the processor. Phase config
is therefore snapshotted at launch, not re-read per phase. All six runs started
at 23:43:47-58, roughly 80 seconds before the earliest possible reinstall, so
each should be executing against the state it captured then - the broken v3 for
the A arm.

**What I cannot establish from here:** the exact wall-clock of the reinstall.
`created_at` is null on the workflow response and there is no `updated_at`, so
the deployment does not expose when a template was last written. The commit time
is a lower bound for the implement/pr-review repair, not necessarily for v3's.

## Effect on P6

P6 predicted v3's `cross-model-review` executes on CLAUDE. That prediction was
made when v3 was measurably broken. It now rests on the snapshot assumption
above rather than on the observed state of the workflow.

This does NOT change the eval pack, which already names the phase transcript as
the only admissible evidence for P6 and explicitly rules out `cost_by_model`.
The transcript will show which harness ran regardless of when the template
changed. P6 is simply less certain than when it was written, and if it scores
wrong the reason may be the repair rather than the reasoning - that distinction
goes in the verdict.

## Note on the experiment's own design

This is the confound the probe was already carrying, moving. Setup declared the
provider loss as confound 1; it has now been fixed underneath the run. A probe
whose baseline condition is repaired mid-flight is a reminder that a shared
deployment is not a frozen environment, and that isolating one variable is
harder when a peer is actively repairing the system under test.
