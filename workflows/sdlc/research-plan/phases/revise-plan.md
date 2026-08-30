# Revise the plan

You have both documents:

- `artifacts/input/research-and-plan.md` - the plan you drafted
- `artifacts/input/cross-model-review.md` - a different model's review of it

## The original problem

$ARGUMENTS

## What to do

Work through the review finding by finding and, for EACH one, do one of:

- **Accept** - fix the plan. Say what changed.
- **Reject** - explain why the reviewer is wrong, with `file:line` evidence.
  A reviewer can be mistaken; deferring to a wrong finding makes the plan worse.

Verify any claim you are unsure about against the code rather than taking
either document's word for it. Both were written by a model; both can be wrong.

## Output

Write the FULL revised plan to `artifacts/output/plan-final.md` - complete and
standalone, not a diff against the first draft. Whoever approves this should
not need to read the other two documents.

End with a short section:

## Review disposition

| finding | accepted / rejected | what changed |

and a one-line **Readiness** statement: is this plan ready to implement, or does
it still need a decision from a human? Say which decision.
