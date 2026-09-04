# Results

**No arm produced a final artifact, so the comparison this probe exists to make
was never made.** See `verdict.md`. The probe is inconclusive for final-plan
quality. Nothing below is a scored prediction; the first table is operational
observation about whether the workflow ran, and the second records what cannot
be scored and why.

Artifacts in `runs/`: `<RUN>_<phase>.json` are phase artifacts, `<RUN>.json` the
execution records. All of it is kept.

## Run outcomes

| Run | Workflow | Target | Outcome | Last committed artifact |
|---|---|---|---|---|
| A1 | research-plan-v3 | `_wiring.py` | failed at phase 3/4 | `plan` (2/4) |
| A2 | research-plan-v3 | `WorkflowExecutionProcessor.py` | failed at phase 3/4 | `plan` (2/4) |
| A3 | research-plan-v3 | `lifecycle.py` | failed at phase 3/4 | `plan` (2/4) |
| B1 | refactor-plan-v1 | `_wiring.py` | cancelled at phase 4/5 | `characterize` (2/5) |
| B2 | refactor-plan-v1 | `WorkflowExecutionProcessor.py` | cancelled at phase 5/5 | `characterize` (2/5) |
| B3 | refactor-plan-v1 | `lifecycle.py` | cancelled at phase 3/5 | `coverage-gate` (1/5) |

Precisely: A1-A3 FAILED at phase 3 of 4; B1 and B3 were CANCELLED before their
final phase; B2 was cancelled DURING phase 5 of 5 and produced no `revise`
artifact. **No B run completed `revise`**, and no `seams` artifact was committed
for any B run.

The pack's literal wording is *"Execution fails before its final phase"*, which
covers A1-A3, B1 and B3 but not B2 - that one was cancelled during its last
phase, and all three B runs are `cancelled` rather than `failed`. An earlier
version claimed all six matched the quoted rule verbatim. They do not. The
broader criterion the pack exists to enforce - no final artifact, so P4 cannot
be scored and no arm can be compared - holds for all six.

## Operational observations: the gate ran and it discriminated

Not scores. These say the workflow executed as designed; they say nothing about
whether the resulting plan is better.

| # | Prediction | What was seen | Evidence, and how far it goes |
|---|---|---|---|
| P1 | v3 runs no coverage command | no coverage command or output in any A `research` artifact | the pack requires the session TRANSCRIPT; absence from a deliverable does not prove no Bash call ran coverage |
| P2 | gated arm runs one, 3/3 | all three `coverage-gate` artifacts contain a coverage invocation AND its output table | consistent with the commands having run, but agent-authored prose is not proof of execution and transcripts were not committed |
| P3 | >=2/3 CHARACTERIZATION TESTS REQUIRED FIRST | 2/3 (B1, B3); B2 `SAFE TO REFACTOR` on measured 96% | the strongest of the three: the pack names the `coverage-gate` artifact itself as P3's evidence path, and those artifacts ARE committed. Still not a score - the executions they came from are invalid |

Separately, from the execution records rather than from any artifact:
`coverage-gate` reached `completed` in 3/3 and `characterize` in 3/3. That the
gate phase runs to completion and emits one of its three verdict headings is
the part of this probe that is not in doubt.

## Not scorable

| # | Prediction | Why there is no score |
|---|---|---|
| P4a | v3 leads with a split | the pack requires the arm's FINAL artifact; none exists. A `plan` artifact is phase 2 of 4 |
| P4b | gated arm leads with test work, >=2/3 | same: no final artifact. The earlier 1/3 was computed over intermediate documents, one of which (B3's `characterize`) is not committed, so it cannot be re-derived from `runs/`. An earlier version recorded it as "partial" against a binary threshold, which was generous scoring of my own prediction; it is now not scored at all |
| P5 | cost 1.2-1.8x baseline | no run completed in either arm |
| P6 | v3 review phase runs on claude | all three died with claude's error text naming `gpt-5.6-sol` - strong circumstantial evidence, but the pack named the transcript as the ONLY admissible source |

## The word count, correctly labelled

| artifact | "characterization" | "coverage" |
|---|---:|---:|
| A1 `plan` | 0 | 0 |
| A2 `plan` | 0 | 0 |
| A3 `plan` | 0 | 5 |
| B1 `characterize` | 18 | 14 |
| B2 `characterize` | 19 | 11 |

These counts are correct and were independently reproduced in review. They are
kept because they are real.

They cannot carry the conclusion, for a reason visible in the column headings:
the B rows are `characterize`-phase artifacts, produced by a prompt that uses
the word "characterization" throughout and explicitly demands characterization
tests. A phase prompted to discuss characterization discussed characterization.
That is a **manipulation check** - evidence the prompt did its job - and it
compares a `characterize` artifact against a `plan` artifact from a different
workflow, so it says nothing about whether the gate changed planning.

An earlier version of this file promoted them to the headline finding and added
that A1 had "no test anywhere in the sequence". That is false. Reproducibly:

    jq -r .content runs/A1_plan.json | grep -ioE '\btests?\b' | wc -l
    -> 60

A1 also runs affected tests after each extraction group and specifies unit
coverage, fitness tests, `just preflight` and CI. The true and much narrower
difference is that A1 prescribes no NEW characterization tests for behaviour
nothing currently pins.

## Why both arms died - neither reason was the variable

- **A arm:** the three review phases died with error text naming
  `gpt-5.6-sol` in a form characteristic of the claude CLI. The stored template
  was independently observed to have lost `agent.provider` to the lossy v0.27.0
  exporter, which would produce exactly this. Strong circumstantial evidence,
  not the transcript the pack requires. Fixed on the deployment since.
- **B arm:** cancelled by me, on a misreading of frozen telemetry that turned
  out to be the platform's own reporting defect (fixed in #1076), not a hang.

## An observation that is NOT a control

B2's `cross-model-review` phase reached `completed` while the three A-arm review
phases did not. That is what the execution records show.

It is tempting to call this a clean control isolating the A-arm failure to a
missing provider, and an earlier version of this file did. It is not one. Which
harness executed either phase is exactly the question the pack says only a
session transcript can answer, and none is committed. `sdlc-refactor-plan-v1`
having been freshly installed rather than round-tripped through the lossy
exporter is a plausible explanation, not a demonstrated one.

## Cost

$19.83 across six runs, none of which completed.
