# Investigate, and write a spec

Your ONLY job is to find out what is true and write it down. You are not
proposing a solution and you are not writing a plan. A later phase plans; if you
start planning here you will stop investigating, because drafting an approach
feels like progress and hunting for evidence that contradicts you does not.

This document is a SPEC: what the system does today, what it must do, and what
is genuinely not known. It is not a sequence of steps.

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
5. Separate what you VERIFIED by reading or running from what you INFERRED.
   Everything inferred is a candidate unknown.

## Write to `artifacts/output/spec.md`

- **What the code does today** - with `file:line` for every claim.
- **Is the problem real?** - confirmed, partly confirmed, or refuted, with the
  evidence that decided it.
- **What must be true of any solution** - the behavioural requirements and the
  invariants it may not break.
- **What already exists** - things a solution should use rather than rebuild.
- **Blast radius** - files, call sites, consumers.
- **Constraints** - ADRs, schema-compatibility rules, existing invariants.
- **Unknowns** - see below. This section is the point of the phase.

## The Unknowns section

Number them: `U1`, `U2`, and so on. A later phase dispatches one subagent per
unknown and tries to settle it by RUNNING something, so a vague unknown burns a
whole subagent and returns nothing.

Each unknown must be:

- **A falsifiable statement**, not a topic. "Artifact collection preserves the
  phase-id directory when the flat alias is absent" is testable. "How artifact
  collection works" is not.
- **Paired with the command or observation that would settle it.** State the
  exact command, and state which observable outcome means true and which means
  false. If the settling evidence is a file that would only exist if the thing
  happened, say which file.
- **Actually unknown.** If ten minutes of grep would answer it, answer it now
  and cite the answer. An unknown that the repository already answers wastes the
  experiment phase and, worse, makes the spec look more uncertain than it is.

If you believe something but cannot cite it, that belief belongs in Unknowns,
not in the body. The goal is a spec someone can maintain a system against, not
a document that looks complete.

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

- Every factual claim carries a `file:line`. A claim you cannot cite becomes an
  unknown instead.
- Do not propose a solution. Do not modify any file outside `artifacts/output/`.
