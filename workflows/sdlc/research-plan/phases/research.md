# Investigate

Your ONLY job is to find out what is true. You are not proposing a solution.
A later phase plans; if you start planning here you will stop investigating,
because writing a plan feels like progress and looking for contradicting
evidence does not.

## The problem as stated

$ARGUMENTS

## What to do

1. Find the code that actually handles this concern - not the code you would
   expect to exist. Record exact `file:line`.
2. Confirm or refute the problem statement AGAINST THE CODE. It may be wrong,
   overstated, or already fixed. Saying so is a successful outcome here.
3. Find what already exists: helpers, constants, tests, prior attempts, and
   anything in `docs/adrs/` that constrains the answer.
4. Find the blast radius - every call site and consumer a change would touch.

## Write to `artifacts/output/research.md`

- **What the code does today** - with `file:line` for every claim.
- **Is the problem real?** - confirmed, partly confirmed, or refuted, with the
  evidence that decided it.
- **What already exists** - things a solution should use rather than rebuild.
- **Blast radius** - files, call sites, consumers.
- **Constraints** - ADRs, schema-compatibility rules, existing invariants.
- **Open questions** - what you could NOT determine, and what would settle it.

## Rules

- Every factual claim carries a `file:line`. A claim you cannot cite goes under
  Open questions instead.
- Mark clearly what you VERIFIED by reading versus what you INFERRED.
- Do not propose a solution. Do not modify any file.
