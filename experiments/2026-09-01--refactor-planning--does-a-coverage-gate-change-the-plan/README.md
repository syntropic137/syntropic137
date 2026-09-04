# Does a coverage gate change what a refactor plan says?

**Slug:** `2026-09-01--refactor-planning--does-a-coverage-gate-change-the-plan`
**Status:** run; **inconclusive for final-plan quality** - see `verdict.md`

> All six runs ended before their final phase, so neither arm produced a final
> plan and the comparison below was never made. The predictions in this file are
> the ORIGINAL preregistration and are left exactly as written; read `verdict.md`
> and `results.md` for what the runs do and do not show.

## Question

When a planning workflow is required to MEASURE test coverage before designing
an extraction, does the resulting plan differ in kind from one produced without
that gate - or does a capable model check coverage anyway, making the gate
ceremony?

Falsifiable form: `sdlc-research-plan-v3` (no gate) and `sdlc-refactor-plan-v1`
(coverage gate first) are run on the same three oversized modules. If the gate
is ceremony, both arms measure coverage and both sequence test work before
extraction. If the gate is load-bearing, only the gated arm does.

## Why this matters (the decision waiting on it)

There are ten in-repo modules over the 750-line fitness threshold. Planning all
of them costs roughly $60 at the observed v3 mean. The choice of which workflow
to spend that on is the decision this probe informs, and it is being made now.

The stronger reason: the platform's product IS workflow quality. "Add a gate
phase" is the cheapest structural intervention available, and we have never
measured whether a gate phase changes output or merely adds a phase.

## FOCUS gate

| Gate | Assessment |
|---|---|
| Fit | #185 and #934 are open refactor issues; the big-file list is active work |
| Organization pull | A ~$60 spending decision waits on the result, today |
| Capability readiness | Deployment reachable; both workflows installed; per-phase cost, tokens and tool-use observable via `/api/v1/events/sessions/{id}/tools` |
| Underlying data | Baseline captured BEFORE this probe: 5 completed v3 runs, mean $5.83, max $8.40 |
| Success | Predicted numbers below, committed before any run |

## Hypothesis

Predictions, each scored later as correct / partial / wrong.

| # | Prediction |
|---|---|
| P1 | v3 executes NO real coverage command in any arm. Predicted 0/3. |
| P2 | refactor-plan-v1 executes a real coverage command in 3/3. |
| P3 | refactor-plan-v1 returns `CHARACTERIZATION TESTS REQUIRED FIRST` on at least 2 of 3 targets. These modules are large, old and I expect them thinly pinned. |
| P4 | v3's primary deliverable is a module split in 3/3. refactor-plan-v1 leads with test work in at least 2/3. |
| P5 | refactor-plan-v1 costs 1.2x-1.8x the v3 baseline mean of $5.83, i.e. $7.00-$10.50 per run. It has five phases against four. |
| P6 | v3's `cross-model-review` phase executes on CLAUDE, not codex, because the reinstall path dropped `agent.provider` (see Setup). Predicted 3/3 claude. |

**Where I expect to be wrong:** P3. If these modules turn out to be well covered,
the gate passes and the two arms converge - which would make the gate cheap
insurance rather than a change in kind. That is the most useful way for this
probe to fail.

## Setup

- **Deployment:** Mac mini, `$SYN_API_URL`, healthy (`mode: full`, 24 projections).
- **Repo under analysis:** `syntropic137/syntropic137` at `53e4ed4c`.
- **Arms:** `sdlc-research-plan-v3` (4 phases) vs `sdlc-refactor-plan-v1` (5 phases, committed in `37e0caed`).
- **Targets** - three in-repo modules over the 750-line fitness threshold, chosen for different shapes:
  1. `apps/syn-api/src/syn_api/_wiring.py` (1582 lines) - composition root, no tracking issue, at its LOC exception limit
  2. `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py` (896) - domain logic, issue #934
  3. `apps/syn-api/src/syn_api/services/lifecycle.py` (907) - service with real I/O
- **Same task string per target**, varying only the workflow. One variable.

### Known confounds, declared before the run

1. **The v3 arm is not the v3 that produced the baseline.** The reinstall path
   dropped `agent.provider` on v3 (measured: `provider=None` on all four phases;
   control: a fresh install of a new id retained `provider='codex'`). So v3's
   cross-model-review phase now defaults to claude while still carrying
   `model: gpt-5.6-sol`. P6 turns this confound into a measurement rather than
   pretending it away. The $5.83 baseline predates the reinstall and is used
   only as a cost anchor, not as a quality comparison.

2. **One pre-hypothesis run exists and is EXCLUDED from evidence.**
   `exec-0c5b9375b9bf` (v3, on issue #185 / `setup.py`) was launched before this
   hypothesis was written. It is not in the eval pack, is not scored, and its
   target is deliberately not one of the three above.

3. **Cost is per-run variable.** The v3 baseline ranged $2.65-$8.40 across five
   runs, so a single-run cost comparison is weak. P5 is scored on the mean of
   three, and is the prediction most likely to be scored `inconclusive`.

## Conditions

| Condition | Workflow | Targets | Runs |
|---|---|---|---|
| A (baseline, no gate) | `sdlc-research-plan-v3` | 3 | 3 |
| B (gated) | `sdlc-refactor-plan-v1` | 3 | 3 |

Six runs. Both arms see identical task strings and the same repo SHA.

## Expected signals

- Tool-use records per phase (`/api/v1/events/sessions/{id}/tools`) show whether `Bash` was used and the transcript shows whether a coverage command ran.
- Phase-level `model` and `cost_by_model` for the review phase (P6).
- The produced artifact's structure: does it lead with tests or with a file layout.

## What would invalidate this run

- A target whose coverage tooling cannot execute in the workspace at all - then P1/P2 measure workspace capability, not workflow design.
- Either workflow failing before its final phase, leaving no artifact to score.
