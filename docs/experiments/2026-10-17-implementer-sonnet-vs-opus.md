# E2: Sonnet 5.5 vs Opus 5.5 as implementer (preregistered 2026-10-17)

Status: APPROVED by the orchestrator on 2026-10-17, with conditions. Wait for
"GO" after the pit stop, which happens after the orchestrator registers both
new workflows. Nothing dispatched.

Conditions:
- The treatment pins the explicit id `claude-sonnet-5-5`, not the alias.
- **Abort rule:** on the FIRST treatment execution, `phases[].model` must read
  `claude-sonnet-5-5`. If it does not, abort the whole experiment.
- Scoring runs on the platform via `eval-implement-score-v1`
  (`workflows/evals/implement-score/`). That workflow is identical for both
  arms, pinned to `claude-opus-5-5`, and does no judging: the verdict is
  `eval_implementer.py`'s exit code.
- Scoring runs count toward the cap of 2 in flight.

## Question

Does claude-sonnet-5-5 make the hidden tests of real fixes pass as often as
claude-opus-5-5? Implement and fix are 44% of implement-workflow spend, and
Sonnet is half Opus's price per token.

## Arms (one variable: the implement model)

- Control: `eval-implement-pinned-v1` (claude, `opus` resolving to claude-opus-5-5).
- Treatment: a new workflow id, `eval-implement-pinned-sonnet-v1`. It is the
  control file with only `model: sonnet` changed. It must be added and
  registered first; the control is not edited.
- Held constant: the cases, the issue text, the prompt, the tools and the image.

## Sample

implementer-seed-v1, all 5 cases, 2 runs per case per arm: 20 executions in
all. Two runs per case, because one run per case cannot separate the model
from run-to-run noise.

## Hypotheses

- H0: equal pass rate. Sonnet becomes the fix-phase candidate for E3.
- H1: Sonnet passes fewer. Opus stays on implement and fix.
- H2: Sonnet passes more or equal at much lower cost. E3 proceeds, and
  implement itself becomes a later candidate.

## Metrics

- Primary: PASS count from `scripts/eval_implementer.py score` (hidden tests).
- Guard: patch size and files touched outside the fix's files (a scope check).
- Secondary: cost and duration.

## Mechanism check

`phases[].model` must read `claude-sonnet-5-5`. A run on Sonnet 5 is excluded,
because the pinned CLI is known to resolve `sonnet` to Sonnet 5. A leak check
per the suite README is also required.

## Decision rule

- Sonnet PASS >= Opus PASS - 1 (out of 10): proceed to E3.
- Sonnet PASS <= Opus PASS - 3: stop; Opus stays.
- Anything in between: INCONCLUSIVE; do not proceed to E3.

## Stop rule

20 scored executions, or the Claude weekly quota for the VPS account below
20%. A platform failure is re-run once.

## Expected cost (API-equivalent, Claude quota only, no Codex)

Estimated from the median production implement phase ($1.92, 43 min, n=25).
- Opus arm: 10 x ~$1.9 = ~$19.
- Sonnet arm: 10 x ~$1.0 = ~$10, assuming similar token counts at half the
  price per token.
- Scoring: 20 x `eval-implement-score-v1` at roughly $0.3-0.5 each = ~$6-10.
- Total ~$40, across 40 executions. With 2 in flight, about 6-8 h of wall
  clock.

## Procedure

1. Launch the implement run for each case, one per arm, alternating arm order.
   Tag every run `eval-research`, `experiment:e2-implementer-sonnet` and
   `arm:control` or `arm:treatment`.
2. Check the first treatment execution's `phases[].model` (the abort rule).
3. When an implement run completes, launch `eval-implement-score-v1` with
   `task=<case id>` and `implement_execution_id=<id>`. If the deployment has
   no platform API access, also pass the patch text as `patch`.
4. Read `score.md` line 1. Record PASS, FAIL or ERROR per execution in the
   Results table below.
5. Read each PASS run's tool trace for leaks (`git log --all`, `git show`,
   `fetch`, `gh`) before counting it (suite README, "Leakage").

## Dependencies and blockers

- The orchestrator must register `eval-implement-pinned-sonnet-v1` and
  `eval-implement-score-v1` on the VPS after the pit stop.
- Whether the VPS grants platform API access to workspaces is unknown. If it
  does not, the patch is passed as an input. A patch containing a triple
  backtick could break the prompt fence: check the scorer's reported sha256
  against the artifact.

## Results

(not yet run)
