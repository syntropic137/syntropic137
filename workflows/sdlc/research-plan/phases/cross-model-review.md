# Review the plan

A different model wrote the plan in `artifacts/input/research-and-plan.md`.
Your value here is disagreement, not agreement.

## The original problem

$ARGUMENTS

## Read the plan, then verify it against the repository

Do not review the plan as prose. Check its claims against the actual code.

Answer explicitly:

1. **Are the `file:line` references real and do they say what the plan claims?**
   A plan citing code that does not exist, or that does something else, is
   worse than a vague one - it looks verified.
2. **Would the approach actually work?** Name the specific place it breaks:
   a call site it missed, an interface that does not exist, an assumption about
   behaviour that the code contradicts.
3. **Is anything already solved?** Existing constants, helpers, or tests the
   plan proposes to recreate.
4. **Does the verification plan actually verify?** A test that would pass with
   the change reverted proves nothing. Name any such test.
5. **What did the plan not consider?** Scope it missed, not style you dislike.

## Rules

- Read-only. Do not modify any file. Do not implement anything.
- Cite `file:line` for every claim you make. You are holding the plan to that
  standard; hold yourself to it.
- Separate BLOCKERS (the plan fails if unaddressed) from IMPROVEMENTS.
- If the plan is sound, say so plainly. Do not manufacture findings to look
  thorough - a review that always finds something teaches the next reader to
  ignore it.

Write to `artifacts/output/review.md`.
