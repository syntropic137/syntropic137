# Plan

Research is done. It is in `artifacts/input/research.md`. Your job is to decide
what to do about it, and nothing else.

## The problem as stated

$ARGUMENTS

## What to do

1. Read the research. Treat its Open questions as real gaps, not as things to
   paper over - if one blocks the plan, say so.
2. Spot-check its load-bearing claims. Another model wrote it and can be wrong;
   a plan built on a wrong finding inherits the error and hides it.
3. Decide the approach, and record what you rejected and why.

## Write to `artifacts/output/plan.md`

- **Problem** - one paragraph, in observable behaviour, not code shape.
- **Approach** - what changes, in what order, with `file:line`.
- **Rejected alternatives** - at least one, with the reason. A reviewer cannot
  evaluate a decision whose alternatives are invisible.
- **Risks** - what could break, and the signal that would tell us it broke.
- **Verification** - the exact commands and assertions that prove it works.
  "Add tests" is not verification; state what each test asserts and what it
  would catch. A test that passes with the change reverted proves nothing.
- **Out of scope** - what this deliberately does not do.
- **Needs a human decision** - anything you should not decide alone.

## Rules

- Plan only. No production code, no commits.
- If the research refuted the problem, say so and stop; do not invent work.
