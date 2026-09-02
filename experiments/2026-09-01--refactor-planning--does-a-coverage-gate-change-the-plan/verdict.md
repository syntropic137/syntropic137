# Verdict: **go** — with the comparison itself compromised

Adopt `sdlc-refactor-plan` for refactor planning. Do not treat the cost or
quality comparison in this probe as settled; it was not cleanly measured.

## Hypothesis scorecard

| # | Predicted | Observed | Score |
|---|---|---|---|
| P1 | v3 runs no coverage command, 0/3 | 0/3 | correct |
| P2 | gated arm runs one, 3/3 | 3/3 | correct |
| P3 | >=2/3 verdicts are CHARACTERIZATION TESTS REQUIRED FIRST | 2/3 | correct |
| P4a | v3 leads with a split, 3/3 | 3/3 | correct |
| P4b | gated arm leads with test work, >=2/3 | 1/3 clearly | **partial** |
| P5 | gated costs 1.2x-1.8x baseline | no run completed in either arm | **inconclusive** |
| P6 | v3's review phase runs on claude, 3/3 | 3/3 | correct |

Five correct, one partial, one inconclusive. **That ratio is a warning, not a
victory** — the correct ones were mostly cheap to predict. P1 and P2 were close
to tautological: one workflow has a coverage phase and the other does not, so of
course only one measures coverage. They confirm the phase executed as written.
They do not show the gate was worth its cost.

## Where I was wrong

**P4b, and it is the interesting miss.** I predicted the gated arm would lead
with test work in at least 2 of 3. Only B2 did. B1 opens with a decomposition
section and reaches its characterization spec in section 3.

The prediction was too crude. "Leads with" measured document ORDER, and order
is a weak proxy for what a plan is about. The thing I should have predicted is
the one the data actually shows: the gated plans are *saturated* with
characterization (18 and 19 mentions) while two of three ungated plans never
mention it once. A word count I did not think to predict separates the arms far
more sharply than the ordering rule I did.

**P3 was right for a reason I did not anticipate.** I predicted the gate would
mostly demand tests because these modules are large and old. It did — but B2
returned SAFE TO REFACTOR on a MEASURED 96%, with two independent test-scope
runs agreeing. The gate is not a rubber stamp that always says no. It
discriminated, which is a stronger result than the prediction.

## What this probe cannot tell you

**Whether the gated plans are better to execute.** Every measure here is
structural — does it measure, what verdict, what words. Nobody has run either
plan. A plan can be saturated with characterization and still be wrong.

**Anything about cost.** P5 is inconclusive, not marginal.

## Why the comparison is compromised, stated plainly

The baseline arm was running a workflow that could not complete. `sdlc-research-plan-v3`
had lost `agent.provider` to the lossy v0.27.0 exporter, so its review phase
executed on claude holding a codex model id and died every time. The A arm never
produced a final revised plan; it was scored on `research` and `plan` only.

The B arm was cancelled mid-flight — by me, on a misreading of frozen telemetry
that turned out to be the platform's own reporting defect and not a hang.

So neither arm ran to completion, for two different reasons, neither of which
was the variable under test. The structural findings survive because they come
from phases that DID complete. The cost and end-to-end quality questions do not
survive and are not answered here.

## The verdict is still go

The class-difference evidence is strong enough to act on despite the above.
Ungated planning of an oversized module produced a document that never mentions
coverage or characterization and whose first step is `wc -l`. That is a plan to
make a file shorter, not to preserve behaviour — and it would have been executed
against modules whose behaviour nothing pins.

## Follow-ups

1. **A clean rerun** on a repaired v3 with no cancellation, to answer P5 and
   whether the gate's plans execute better. Its own hypothesis; not a rerun of
   this pack.
2. **v1 vs v2 (sonnet vs opus)** — the pair differs in exactly one field and is
   the cost-versus-quality question the owner named.
3. **Execution trial.** Take one gated plan and one ungated plan for the same
   module, run both, and count the regressions. That is the question this probe
   raises and cannot answer.
