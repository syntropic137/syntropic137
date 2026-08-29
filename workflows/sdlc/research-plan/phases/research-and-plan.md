# Research and plan

You are producing a PLAN, not an implementation. Write no production code.

## The problem

$ARGUMENTS

## What to do

1. Read the repository before proposing anything. Find the code that actually
   handles this concern - not the code you would expect to exist. Note exact
   `file:line` references; a plan that cannot be traced to real code cannot be
   reviewed.
2. Establish what is already true. Existing tests, existing constants, prior
   attempts, and anything in `docs/adrs/` that constrains the answer. A plan
   that reinvents something the repo already has is worse than no plan.
3. Decide the approach, and say what you rejected and why. A reviewer cannot
   evaluate a decision whose alternatives are invisible.
4. Write the plan to `artifacts/output/plan.md`.

## The plan must contain

- **Problem** - one paragraph, in terms of observable behaviour, not code shape.
- **Evidence** - the `file:line` references that establish the problem is real.
  If you could not confirm it from the code, say so explicitly; do not assert.
- **Approach** - what changes, in what order.
- **Rejected alternatives** - at least one, with the reason.
- **Risks** - what could break, and what would tell us it broke.
- **Verification** - the specific commands and assertions that prove the change
  works. "Add tests" is not a verification plan; name what they assert.
- **Out of scope** - what this deliberately does not do.

## Rules

- Distinguish what you VERIFIED from what you INFERRED. Mark inferences as such.
  A confident plan built on an unchecked assumption is the expensive failure.
- If the problem statement is ambiguous, state the ambiguity and plan for the
  reading you chose. Do not silently pick one.
- No code changes. No commits. No branches. The only output is the plan file.
