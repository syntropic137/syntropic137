# Plan

The spec is settled. It is at `artifacts/input/revise-after-experiment/spec.md`,
and it carries facts that were MEASURED, not reasoned about. Your job is to
decide what to do about it, and nothing else.

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

1. Read the spec, including its **Overturned by experiment** and **Still
   unknown** sections. Those two sections constrain the plan more than the body
   does.
2. Spot-check its load-bearing claims. Another model wrote it and can be wrong;
   a plan built on a wrong finding inherits the error and hides it. You have
   Read, Grep and Glob only, so check citations against the files and check
   measured facts against the verdict file that recorded the command output.
3. Decide the approach, and record what you rejected and why.

## Every risky decision cites a verdict

For each decision that could be wrong in a way that costs a rewrite, name the
experiment verdict that supports it: the unknown number and the verdict file.
The point of the previous phases was to buy this, so spend it. A decision with
no citation is a decision made on belief, and it should say so rather than sit
next to measured ones looking equally solid.

## Say what still rests on an unknown

A separate, explicit section. For every unknown the spec still lists as STILL
UNKNOWN, state which step of this plan depends on it, and what happens to the
plan if it turns out the other way. If a step cannot be planned without it, say
that the step is blocked rather than guessing and moving on.

This section is not a disclaimer. It is the list of places the implementation
will discover a surprise, and naming them in advance is the difference between a
plan that adapts and one that gets abandoned.

## Write to `artifacts/output/plan.md`

- **Problem** - one paragraph, in observable behaviour, not code shape.
- **Approach** - what changes, in what order, with `file:line`.
- **Evidence** - each risky decision, and the unknown number and verdict file
  behind it.
- **Resting on an unknown** - as above.
- **Rejected alternatives** - at least one, with the reason. A reviewer cannot
  evaluate a decision whose alternatives are invisible. If an experiment is what
  killed an alternative, cite it - that is the strongest kind of rejection.
- **Risks** - what could break, and the signal that would tell us it broke.
- **Verification** - the exact commands and assertions that prove it works.
  "Add tests" is not verification; state what each test asserts and what it
  would catch. A test that passes with the change reverted proves nothing, and
  the experiment phase already showed you what a control looks like.
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
- If the spec refuted the problem, say so and stop; do not invent work.
- Plan for the code to be maintainable afterwards, not for this plan to look
  complete. A step that is easy to write and leaves the system harder to change
  is a bad step even if every box is ticked.
