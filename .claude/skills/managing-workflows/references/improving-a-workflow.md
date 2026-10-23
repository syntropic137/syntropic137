# Improving a workflow

A loop from a measured gap to a promoted default. The detailed experiment
design (arms, sample sizes, judging) lives in `workflow-experimentation`; this
is the manager's view of where each step fits and what it produces.

## 1. Name the gap with evidence

State it as a number with its scope, shaped like (illustrative) "implement-v3
spent N% of fix rounds on CI flakes across M runs, <start> to <end>". A gap without a number is
an opinion. Sources: session start measurements, escaped bugs, retros, paper
cuts, the feedback queue.

Classify it before fixing it:

| Class | Example | Usual lever |
|---|---|---|
| quality: misses | verifier certified a bug | prompt checks, verifier model, a new eval case |
| quality: false blocks | verifier blocked a clean change | prompt evidence rules, control review |
| wasted rounds | fix round spent on a flake | phase precheck, routing evidence to the orchestrator |
| cost | one phase dominates spend | model routing with eval proof, smaller context, early exit |
| time | phase waits or retries | timeouts sized to agent work, fan-out inside one phase (parallel phases are not supported: `require_supported_execution_type`) |
| harness | vendor quota, provisioning | not a workflow change; file an issue |

Harness failures are not workflow problems. Do not tune prompts against them.

## 2. Make sure an eval can see it

If no suite case reproduces the gap, write one first (`learning-loop`,
`evals.md`). A change you cannot measure cannot be promoted, so this step is
not optional.

## 3. Preregister

Write `EXPERIMENT.md` beside the arm, following
`workflows/sdlc/implement-v4-precheck/EXPERIMENT.md`. Include: the one change,
the hypothesis, the suite and version, the metric that decides it, the
threshold, and what would make it a no-go. Writing the threshold after the
results is fitting a story to noise.

## 4. Build the arm

A new workflow id that differs in exactly one variable
(`building-a-workflow.md`). Keep the baseline unchanged.

## 5. Run baseline and arm on the same suite

Same suite version, same cases, repeats where the result is noisy. Record
cost and wall-clock alongside the score, because the arm can win on quality
and lose on cost, and you need both to decide.

## 6. Decide and record

- go: promote in `CURRENT-BESTS.md`, mark the old default `superseded`, add the
  finding to `FINDINGS-LEDGER.md`, and update this skill's dated section if the
  default workflow changed;
- no-go or inconclusive: record it anyway, because a negative result stops the
  next session from repeating the experiment.

## 7. Confirm in production

After promotion, check the next real runs against the session-start numbers.
An eval win that does not show in production means the suite does not
represent the work; fix the suite.
