# Verdict: **inconclusive for final-plan quality**

The probe asked whether a coverage gate changes what a refactor plan says. It
cannot answer that. No run in either arm produced a final plan, so the two arms
have never been compared on the thing the question is about.

What the runs DO show is narrower and worth keeping: the gate executes, it
returns a verdict rather than rubber-stamping, and the phases behind it produce
characterization-focused intermediate work. That is an operational result about
the workflow running as designed. It is not a result about plan quality, and
this file previously treated the two as interchangeable.

Recorded rather than deleted, because the way it failed is the useful part.
The run data in `runs/` is unchanged.

## Why no comparison is possible, by the pack's own rule

`eval-pack.md` states under "What invalidates a run": *"Execution fails before
its final phase."*

- A1, A2, A3 FAILED at phase 3 of 4. Last committed artifact: `plan` (phase 2).
- B1 and B3 were CANCELLED before their final phase.
- B2 was cancelled DURING phase 5 of 5 and produced no `revise` artifact.

The quoted wording literally covers five of the six; B2 was cancelled during
its last phase, not before it, and all three B runs are `cancelled` rather than
`failed`. The criterion the rule exists to enforce holds for all six: **no arm
produced a final artifact.** The B arm's committed artifacts stop at
`characterize` (phase 2 of 5); no `seams` or `revise` artifact exists for any B
run, and B3's `characterize` was never committed either.

An earlier version of this file scored P4 anyway and returned **go**, justified
by a rule invented after seeing the data ("structural findings survive because
they come from phases that DID complete"). The frozen pack contains no such
exception, and P4 explicitly requires each arm's *final* artifact.

Inventing a salvage rule after the run is precisely the anti-pattern the
two-commit rule exists to prevent. Freezing the pack and then reading past it
is worse than not freezing it, because it produces a result that looks
preregistered and is not.

## What IS supportable: the gate runs, and it discriminates

These are operational observations about execution, not scored predictions.
They are stated here because they are the part of the probe that survives, and
because they are what a decision to run the workflow again would rest on.

- **The gate executes.** `coverage-gate` reached `completed` in 3 of 3 B runs
  (`runs/B{1,2,3}.json`). This comes from the execution records, not from
  agent-authored prose.
- **It returns a verdict, and not the same one every time.** B1 and B3 emitted
  `# VERDICT: CHARACTERIZATION TESTS REQUIRED FIRST`; B2 emitted
  `# VERDICT: SAFE TO REFACTOR`, on a measured 96% with two independent
  test-scope runs agreeing. Choosing among the three headings is a decision the
  phase made; it is the one place in the workflow where the output is not
  simply the prompt restated. The gate's own artifact is the evidence path
  `eval-pack.md` names for P3, and it is committed.
- **The pipeline reliably reaches characterization work.** `characterize`
  completed in 3 of 3, and its artifacts are substantively about
  characterization tests.

The third of those carries the least weight, and the reason is in the next
section.

## What is NOT supportable

- **That the final refactor plans differ in kind.** No gated run produced a
  final plan. There is nothing to compare against the A arm, and the A arm has
  no final plan either.
- **That the gated plan is better.** Same reason, and `eval-pack.md` already
  puts plan quality out of scope for this probe's method.
- **P4, in any form.** Not scored. The earlier P4b score of 1/3 was computed
  over intermediate documents, one of which (B3's `characterize`) is not
  committed, so it cannot even be re-derived from what is in `runs/`.
- **P1, P2, P6** name the session transcript as the admissible evidence, and
  only artifacts and execution JSON were committed. The `coverage-gate`
  artifacts do contain coverage invocations and their output, which is
  consistent with the commands having run - but agent-authored prose describing
  a command is not proof it ran, and that distinction is the entire point of
  P1/P2.
- **P5** inconclusive was honest and stands.

## The headline finding was prompt-label leakage

The earlier version led with a word count: two of three ungated plans never say
"characterization" or "coverage", while both gated documents say
"characterization" 18-19 times. The counts are numerically correct and were
independently reproduced in review. They are kept in `results.md`.

The interpretation was not correct. The B documents counted are
`characterize`-phase artifacts, produced by a prompt that repeatedly uses the
word and explicitly demands characterization tests. They are not plans and not
the B arm's final deliverable. The A documents are generic `plan` artifacts. So
the count measures whether a phase followed its own prompt, not whether
measuring coverage changed what planning is about.

That is a manipulation check. It was promoted to the strongest finding. A
vocabulary count over words the treatment prompt supplies cannot carry a
conclusion about the treatment, however large the gap.

**And the supporting claim was false.** The earlier results said A1's plan had
"no test anywhere in the sequence" and was "a plan to make a file shorter, not
to preserve behaviour". A1's plan contains 60 occurrences of
`\btests?\b` (`jq -r .content runs/A1_plan.json | grep -ioE '\btests?\b' | wc -l`),
runs affected tests after each extraction group, and carries a verification
section specifying unit coverage, targeted tests, fitness tests,
`just preflight` and CI. What it does not do is prescribe NEW characterization
tests for behaviour nothing currently pins - a real and much narrower
distinction.

I searched for two words, found zero, and wrote as though that meant no tests.

## Adopting the workflow is an engineering judgment, not this probe's result

`sdlc-refactor-plan` ships in this PR on the argument that a refactor without a
behavioural net is a rewrite, which is a design position that stands on its own.
This experiment is NOT evidence for it and must not be cited as such. No
recommendation to adopt, or not to adopt, is made here.

## What would settle it

The question is still open and still cheap to answer. To close it:

1. **Three matched pairs, run to completion.** Same three targets, same task
   strings, both arms, every run reaching its final phase. Repair the baseline
   arm's provider defect first and do not cancel. Six completed runs is the
   minimum; anything short of a final artifact in both arms of a pair makes
   that pair unusable, exactly as here.
2. **Score P4 on the frozen rule, and score it first.** `eval-pack.md`'s P4
   already says how: *"Judged on the FIRST actionable section, not on whether
   tests are mentioned anywhere."* Read each arm's final artifact, find its
   first actionable section, and record whether it specifies tests to write or
   proposes a module layout. Do this **before looking at any word count**, so
   the count cannot inform the judgement it is supposed to corroborate.
3. **Then, and only then, look at vocabulary** - as a manipulation check on
   whether the prompts did their job, never as the finding.
4. **Ablate the gate, not the workflow.** The treatment changed five prompts,
   not one gate. Identical downstream prompts, with the measured-coverage
   artifact present or absent, is the only way to attribute an effect to the
   gate rather than to the four other prompts that came with it.
5. **Commit the transcripts**, or downgrade any prediction that depends on them
   to not-independently-verifiable, as P1, P2 and P6 are downgraded here.
