# Plan

Research is done. It is in `artifacts/input/research.md`. Your job is to decide
what to do about it, and nothing else.

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
- If the research refuted the problem, say so and stop; do not invent work.

## What a good plan optimises for

The plan is judged by what the resulting code will cost to live with, not by how
quickly it can be executed. Design for reliability, maintainability and
scalability - those are the actual goals; "it works" is the floor, not the bar.

- **Propose deep modules.** A unit earns its existence by the ratio of
  functionality provided to interface complexity (Ousterhout, *A Philosophy of
  Software Design*). If your plan adds three thin layers where one honest
  interface would do, it has added names and files without hiding anything.
- **Put boundaries where change stops.** If a likely future change would ripple
  through every caller, the boundary is in the wrong place. Say where you expect
  change to come from and check the seams are there.
- **Design special cases out rather than in.** A branch added for one caller is
  a permanent cost to everyone who reads that function afterwards.
- **Never plan two places that must agree without a mechanism forcing them to.**
  They will drift. This repository has been bitten by exactly that.

State the maintenance cost of your approach explicitly, and name the alternative
you rejected and why. A plan that only argues for itself has not been designed,
it has been justified.
