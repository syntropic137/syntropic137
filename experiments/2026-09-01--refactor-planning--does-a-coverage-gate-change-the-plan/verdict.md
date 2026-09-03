# Verdict: **invalid**

This probe does not support a conclusion. Every one of its six runs is invalid
under its own frozen eval pack, and the scoring below was salvaged from
intermediate phases the pack does not permit scoring.

Recorded as invalid rather than deleted, because the way it failed is the
useful part.

## Why invalid, by the pack's own rule

`eval-pack.md` states under "What invalidates a run": *"Execution fails before
its final phase."*

- A1, A2, A3 failed at phase 3 of 4.
- B1, B2, B3 were cancelled at phases 3-5 of 5.

Six of six. The earlier version of this file scored six predictions anyway and
returned **go**, justified by a rule invented after seeing the data
("structural findings survive because they come from phases that DID
complete"). The frozen pack contains no such exception, and P4 explicitly
requires each arm's *final* artifact, which does not exist for either arm.

Inventing a salvage rule after the run is precisely the anti-pattern the
two-commit rule exists to prevent. Freezing the pack and then reading past it
is worse than not freezing it, because it produces a result that looks
preregistered and is not.

## The headline finding was prompt-label leakage

The earlier version led with a word count: two of three ungated plans never say
"characterization" or "coverage", while both gated documents say
"characterization" 18-19 times. The counts are numerically correct and were
independently reproduced in review.

The interpretation was not. The B documents counted are `characterize`-phase
artifacts, produced by a prompt that repeatedly uses the word and explicitly
demands characterization tests. They are not plans and not the B arm's planning
phase. The A documents are generic `plan` artifacts. So the count measures
whether a phase followed its own prompt, not whether measuring coverage changed
what planning is about.

That is a manipulation check. It was promoted to the strongest finding.

**And the supporting claim was false.** The earlier results said A1's plan had
"no test anywhere in the sequence" and was "a plan to make a file shorter, not
to preserve behaviour". A1's plan mentions test/pytest/verification **119
times**, runs affected tests after each extraction group, and carries a
verification section specifying unit coverage, targeted tests, fitness tests,
`just preflight` and CI. What it does not do is prescribe NEW characterization
tests for behaviour nothing currently pins - a real and much narrower
distinction.

I searched for two words, found zero, and wrote as though that meant no tests.

## What the evidence actually cannot support

- **P1, P2, P6** require session transcripts as admissible evidence. Only
  artifacts and execution JSON were committed. Agent-authored prose describing
  a command is not proof the command ran, and absence of a word from a
  deliverable is not proof a Bash call did not invoke coverage.
- **P4** requires final artifacts. None exist for either arm.
- **P4b** was scored "partial" against a preregistered threshold of >=2/3 with
  an observation of 1/3. A missed binary threshold is wrong, not partial. The
  softening was generous scoring of my own prediction.
- **P5** inconclusive was honest and stands.

## What survives as a hypothesis, not a result

`coverage-gate` discriminated rather than rubber-stamping: it returned
CHARACTERIZATION TESTS REQUIRED FIRST twice and SAFE TO REFACTOR once, the
latter on a measured 96% with two independent test-scope runs agreeing. That is
worth testing properly. It is not established here.

## Adopting the workflow is an engineering judgment, not this probe's result

`sdlc-refactor-plan` ships in this PR on the argument that a refactor without a
behavioural net is a rewrite, which is a design position that stands on its own.
This experiment is NOT evidence for it and must not be cited as such.

## Follow-up: what a valid probe looks like

1. **Both arms must complete.** Repair the baseline first; do not cancel.
2. **Ablate the gate, not the workflow.** The treatment changed five prompts,
   not one gate. Identical downstream prompts, with the measured-coverage
   artifact present or absent, is the only way to attribute an effect to the
   gate.
3. **Preregister a semantic rubric**, blind-scored. Never a vocabulary count
   over treatment-specific words.
4. **Commit the transcripts**, or downgrade any prediction that depends on them
   to not-independently-verifiable.
