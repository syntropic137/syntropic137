# Review the plan against the spec and the measurements

A different model wrote this plan from a spec whose unknowns were tested. Your
value is disagreement, not agreement. You have:

- `artifacts/input/plan/plan.md` - the proposed approach
- `artifacts/input/revise-after-experiment/spec.md` - the measured spec
- `artifacts/input/experiment/experiments/` - the per-unknown verdict files

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

## The problem as stated

$ARGUMENTS

## The two checks this phase exists for

1. **Does the plan contradict a measured result?** Read the verdict files
   themselves, not the plan's description of them. For every step, ask whether an
   experiment already showed the thing it assumes to be false. This is the most
   expensive error available here: the measurement was paid for and then ignored,
   so the plan looks evidence-backed while resting on a refuted claim.

2. **Does the plan rest on an unknown nobody resolved?** Cross-check the plan's
   "Resting on an unknown" section against the spec's STILL UNKNOWN list and
   against the verdict files that exist. Two failures to look for:
   - a step depending on an open unknown that the plan does not list there
   - a plan citing an unknown as RESOLVED when no verdict file says so, or when
     no verdict file exists at all. A missing verdict is not a passing one.

## Then the ordinary checks

3. **Are the `file:line` citations real, and do they say what is claimed?**
   A plan citing code that does not exist, or that does something else, is worse
   than a vague one - it looks verified.
4. **Would the approach actually work?** Name the specific place it breaks: a
   call site it missed, an interface that does not exist, an assumption the code
   contradicts.
5. **Is any of this already solved?** Existing helpers, constants or tests the
   plan proposes to rebuild.
6. **Does the verification plan actually verify?** Name any test that would still
   pass with the change reverted. The experiment phase ran controls; the
   verification section should meet the same bar.
7. **What did it not consider?** Missing scope, not style you dislike.

## Write to `artifacts/output/review-plan.md`

Separate **BLOCKERS** (the plan fails if unaddressed) from **IMPROVEMENTS**.
Findings that fall under checks 1 and 2 are blockers by default; if you think one
is not, say why.

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
- Cite `file:line`, or the verdict file, for every claim. You are holding the
  plan to that standard.
- Judge the plan on whether the system is maintainable after it, not on whether
  it is well presented.
- If the plan is sound, say so plainly. Do not manufacture findings to look
  thorough - a review that always finds something teaches people to ignore it.
  But a review reporting no findings has usually not looked, so state what you
  actually checked and which verdict files you read.
