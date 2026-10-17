# E2: Sonnet 5.5 vs Opus 5.5 as implementer (preregistered 2026-10-17)

Status: PROPOSED, not approved, nothing dispatched.

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
- Total ~$30. With 2 runs in flight, about 4 h of wall clock.

## Dependencies and blockers

- The treatment workflow does not exist yet.
- Scoring runs `eval_implementer.py score` inside a workspace. It cannot run
  locally: there is no local docker under my limits. The orchestrator must
  route scoring (for example as a workspace phase).

## Results

(not yet run)
