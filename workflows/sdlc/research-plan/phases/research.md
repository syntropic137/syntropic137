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

- Every factual claim carries a `file:line`. A claim you cannot cite goes under
  Open questions instead.
- **A claim that something does NOT exist carries the command that shows it,
  with its real output.** "Dead code, no callers", "there is no such channel",
  "the submodule is unpopulated" cannot carry a `file:line` by construction, so
  the rule above does not constrain them -- and they are the claims a later
  phase leans hardest on. Paste the search:

      $ grep -rn "\.clone(" packages/ apps/ --include="*.py" | grep -v test
      (no output)

  An unchecked absence has already shipped in this workflow's output: a plan
  rejected a correct architectural blocker because "the submodule is
  unpopulated", when one `ls` showed two harness packages in it. Every
  citation in that plan resolved. Absence is where the checking stops.
- Mark clearly what you VERIFIED by reading versus what you INFERRED.
- Do not propose a solution. Do not modify any file.
