# Review the plan

A different model researched and planned this. Your value is disagreement, not
agreement. You have:

- `artifacts/input/research.md` - the investigation
- `artifacts/input/plan.md` - the proposed approach

## The problem as stated

$ARGUMENTS

## Verify against the repository, not against the prose

1. **Are the `file:line` citations real, and do they say what is claimed?**
   A plan citing code that does not exist, or that does something else, is
   worse than a vague one - it looks verified.
2. **Would the approach actually work?** Name the specific place it breaks: a
   call site it missed, an interface that does not exist, an assumption the
   code contradicts.
3. **Is any of this already solved?** Existing helpers, constants or tests the
   plan proposes to rebuild.
4. **Does the verification plan actually verify?** Name any test that would
   still pass with the change reverted.
5. **What did it not consider?** Missing scope, not style you dislike.

## Write to `artifacts/output/review.md`

Separate **BLOCKERS** (the plan fails if unaddressed) from **IMPROVEMENTS**.

## Rules

- Read-only. Modify nothing. Implement nothing.
- Cite `file:line` for every claim. You are holding the plan to that standard.
- If the plan is sound, say so plainly. Do not manufacture findings to look
  thorough - a review that always finds something teaches people to ignore it.
