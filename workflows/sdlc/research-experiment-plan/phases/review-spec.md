# Review the spec

A different model investigated and wrote this spec. Your value is disagreement,
not agreement. You have `artifacts/input/research/spec.md` - the investigation
and its numbered unknowns.

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

## The problem as stated

$ARGUMENTS

## Attack the premise

1. **Is the problem real?** The spec reached a verdict on that. Check it against
   the code. If the spec confirmed a defect that does not exist, that is the
   single most valuable finding you can make, because every later phase inherits
   it and none of them re-check it.
2. **Are the `file:line` citations real, and do they say what is claimed?**
   A spec citing code that does not exist, or that does something else, is worse
   than a vague one - it looks verified.
3. **Is any stated fact actually unverified?** Find sentences presented flatly
   that no citation supports. Those are inferences wearing the clothes of
   findings, and they should be unknowns instead. Name each one.
4. **What is missing?** Call sites, consumers, ADRs or constraints the spec did
   not reach.

## Attack the unknowns, one by one

The next phase spends a subagent on each unknown, so a bad unknown has a
measurable cost. For every numbered unknown, say which of these it is:

- **Already answered** - the repository settles it. Give the `file:line` or the
  command that answers it. This one should be deleted, not tested.
- **Not falsifiable** - a topic rather than a claim, or with no stated command
  and no stated outcome that would mean false. Say what it should be rephrased
  to.
- **Well formed** - a claim, with a command, with a distinguishable outcome.
  Say so plainly.

Then: **which unknown is missing?** Look for load-bearing assumptions the spec
never marked as uncertain. Propose it in the same falsifiable form you are
demanding: a claim, the command, the outcome that would mean false.

## Write to `artifacts/output/review.md`

Separate **BLOCKERS** (the spec is wrong or unusable if unaddressed) from
**IMPROVEMENTS**. Include the per-unknown table and any unknowns you are adding.

## Citing code

Every `file:line` reference MUST be the path from the repository root, exactly
as `git ls-files` prints it - for example
`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/value_objects.py:85`,
never `_shared/value_objects.py:85`.

An abbreviated path is not a smaller version of a citation, it is an unusable
one. `_shared/value_objects.py` matches four bounded contexts in this
repository and identifies none of them, so a reader cannot follow it and a
checker cannot verify it. Measured across three runs: every cited file was
real, and up to 100% of citations were unusable purely because of this.

## Rules

- Read-only. Modify nothing. Implement nothing.
- Cite `file:line` for every claim. You are holding the spec to that standard.
- If the spec is sound, say so plainly. Do not manufacture findings to look
  thorough - a review that always finds something teaches people to ignore it,
  and a review that reports no findings has usually not looked. Say which of
  those two you are.
