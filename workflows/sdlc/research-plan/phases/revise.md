# Revise

You have all three prior phases:

- `artifacts/input/research.md`
- `artifacts/input/plan.md`
- `artifacts/input/cross-model-review.md`

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

## The problem as stated

$ARGUMENTS

## What to do

Work through the review finding by finding. For EACH one, either:

- **Accept** - change the plan, and say what changed.
- **Reject** - explain why the reviewer is wrong, with `file:line` evidence.

Rejecting is expected. A reviewer can be mistaken, and deferring to a wrong
finding makes the plan worse while looking responsive. Check anything you are
unsure about against the code rather than trusting either document.

## Write to `artifacts/output/plan-final.md`

The COMPLETE revised plan, standalone. Whoever approves it should not need to
read the other three documents.

End with:

## Review disposition

| finding | accepted / rejected | what changed |

## Readiness

One line: ready to implement, or blocked on a specific human decision - name it.

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
