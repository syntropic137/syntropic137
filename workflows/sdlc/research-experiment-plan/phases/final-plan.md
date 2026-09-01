# Final plan

You have everything the workflow produced:

- `artifacts/input/plan/plan.md` - the plan you drafted
- `artifacts/input/review-plan/review-plan.md` - a different model's review
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

## What to do

Work through the review finding by finding. For EACH one, either:

- **Accept** - change the plan, and say what changed.
- **Reject** - explain why the reviewer is wrong, with `file:line` evidence, or
  with the verdict file that settles it.

Rejecting is expected. A reviewer can be mistaken, and deferring to a wrong
finding makes the plan worse while looking responsive. Where a finding and a
measurement disagree, the measurement wins: check the verdict file yourself
rather than trusting either document's account of it.

Any finding of the form "this contradicts a measured result" or "this rests on
an unresolved unknown" cannot be rejected on reasoning alone. Reject it only by
pointing at the verdict file that shows otherwise, or accept it.

## Write to `artifacts/output/plan-final.md`

The COMPLETE plan, standalone. Whoever approves this should not need to read the
other documents, though every risky decision should still point at the verdict
file behind it so they CAN. It contains, at least:

- **Problem**, **Approach** (with `file:line`), **Rejected alternatives**,
  **Risks**, **Verification**, **Out of scope**
- **Evidence** - each risky decision and the unknown number and verdict file
  that supports it
- **Resting on an unknown** - each step that depends on something still open,
  what blocked it, and what happens if it goes the other way

Then end with:

## Review disposition

| finding | accepted / rejected | what changed |

Every finding in the review gets a row. A finding silently dropped looks
identical to one that was considered and rejected, and only one of those is
honest work.

## Readiness

One line: ready to implement, or blocked on a specific human decision - name it.
If a still-open unknown makes a step unsafe to start, that is a block, and saying
so is the correct outcome. This workflow exists to reduce uncertainty, not to
manufacture the appearance of a settled plan.

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

- Plan only. No production code, no commits.
- The deliverable is a plan that leaves the system maintainable, not one that
  looks complete. A verification step that would pass with the change reverted
  is worse than no verification step, because it will be believed.
