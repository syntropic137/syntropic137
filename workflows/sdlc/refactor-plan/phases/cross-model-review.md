---
timeout-seconds: 1800
---

Adversarially review a refactor plan produced by a different model. Read the
coverage verdict, the characterization spec and the extraction plan in your
input artifacts.

## The task under review

$ARGUMENTS

## If the gate said DO NOT REFACTOR

There is no extraction plan to review, and that is correct rather than a
failure. Review the VERDICT instead: is it earned by the evidence, or is it an
excuse? An unjustified refusal is as costly as an unjustified go-ahead. Then
stop - do not review a plan that should not exist.

## Otherwise, attack these, hardest first

1. **Is the coverage verdict earned?** Did the gate MEASURE, or estimate and
   dress it up? If it reported a percentage, is there real tool output behind
   it? A plan built on an invented coverage number is worthless no matter how
   good the structure is.

2. **Would the characterization tests actually catch the breakage?** For each
   proposed extraction, find a way the move could change behaviour that no
   specified test would notice. Near-miss tests that fail safe for the wrong
   reason are the specific danger.

3. **Are the seams real?** A "seam" that still requires editing the code under
   test to substitute a collaborator is not a seam. Check that each one can
   actually be controlled from a test.

4. **Is the sequence honest?** Take any step and ask whether the build is really
   green after it alone. Find the step that secretly requires the next one.

5. **Does the split reduce coupling or just move it?** Modules that all import
   each other are one module with extra files. Look for a proposed layout where
   the dependency graph is still a clique.

6. **What does the plan not say?** Missing: rollback, the behaviour nobody
   tests, the caller outside this repo, the import that other tooling depends on.

## Rules

- Read the actual source before agreeing with a claim about it.
- For each finding: the concrete failure, the root cause, a SPECIFIC fix, and
  how to verify the fix.
- Rank by severity. Say plainly when a section is sound - do not manufacture
  findings to look thorough.
- Do not rewrite the plan. Review it.

Write your review to the output directory as markdown.
