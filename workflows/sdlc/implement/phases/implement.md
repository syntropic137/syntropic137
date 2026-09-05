# Make the change

$ARGUMENTS

The bootstrap report is at `artifacts/input/bootstrap.md`. **If it says the task's
premise is false, stop. Change nothing** and report that. Do not try to salvage
the task by reinterpreting it.

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

## Scope

Make the change the task describes, and the whole of it. If the task names two
files but the same defect exists in four, fix four and say so - a fix that leaves
identical instances of the same bug behind is not a fix, it is a carve-out. If
that widens the change beyond what the task authorised, state the widening
explicitly rather than doing it silently.

Do not touch anything under `.github/`. Pushes carrying workflow changes are
rejected by the platform's credential, deliberately, so a change there cannot be
delivered from here. If the task requires one, stop and say so.

## What "done" means here

The deliverable is not a change that passes. It is a change the next person can
live with. Those come apart constantly, and the second one is what you are being
asked for.

**Prefer a deep module to a shallow one.** A module earns its existence by the
ratio of the functionality it provides to the complexity of its interface
(Ousterhout, *A Philosophy of Software Design*). A class that adds a method per
caller, a helper that only forwards arguments, or a wrapper whose signature
mirrors the thing it wraps are all shallow - they add a name and a file without
hiding anything. Prefer one honest interface over three thin layers.

**Hide the decision, not just the code.** Information hiding means a caller does
not need to know how you decided, only what you decided. If changing your
implementation would force every caller to change too, the boundary is in the
wrong place. The clearest test: can you state what this unit does without
describing how it works? If not, the interface is leaking.

**Special cases are where complexity accumulates.** A branch added to satisfy one
caller becomes a branch everyone must reason about forever. Ask whether the case
can be made to not exist rather than handled - that is usually a better change
and almost always a smaller one.

**Complexity is what it costs the reader, not what it cost you.** Code that took
an hour to write and takes an hour to understand is expensive code, however
correct. Optimise for the person debugging it at 2am, who will not have your
context.

This is what reliability, maintainability and scalability actually rest on. A
change that is correct today and incomprehensible in six months has borrowed
against all three.

## On the temptation to make it look done

You will sometimes find that the honest change is larger, or harder, or reveals
that the task's premise is shaky. The strong pull at that moment is to produce
something that LOOKS complete: a test that asserts what you already know is
true, a narrower fix that leaves the real defect in place, a claim in the report
that the tests pass when you ran a subset.

That is the worst possible outcome, worse than stopping. A change that looks
finished gets merged; a change that stops gets attention. Every guard in this
workflow - the mutation requirement, the independent verify phase, the
cross-model review - exists because that pull is real and strong.

So: report what you actually did, state what you could not do, and never write a
number you did not read from a command's output. If you are stuck, being stuck
is a legitimate and useful result.

## Tests

Write tests that would fail without your change. The specific trap in this
codebase: a value written correctly and dropped one hop later, at a constructor
that does not pass it or a serializer that omits it. Those hops pass every test
that checks the objects at either end. So test the thing that CONSUMES your
change, not the object you just edited.

A fixture value must be one that could not have arisen without your change. A
default asserted in its default direction proves nothing.

## Start from current main

**Before you write anything, merge `origin/main` into your working branch** (or
branch from it, if you are starting fresh):

```
git fetch origin
git merge origin/main
```

Never rebase, and never force push - this repository merges main into feature
branches, in that direction, always.

This is not hygiene. The gate you are required to run in the next phase lives in
`main`'s justfile, and a branch that predates it does not have the recipe at all:

```
just preflight-agent
error: Justfile does not contain recipe `preflight-agent`
```

That happened on a real rework: the implement phase branched from the PR's old
base, pushed correct work, and the verify phase then refused to certify it
because the mandated gate did not exist in the revision it checked out. The work
was fine; it was unverifiable. If the merge conflicts, resolve it - a rework that
cannot be verified against current main is not finished.

## If you are reworking an existing PR, use its branch

When the task names a PR to rework, **check out that PR's head branch and push
back to it**, so the review, its findings, and your fix stay on one thread:

```
gh pr checkout <number>
```

Opening a second branch for the same change splits the discussion, leaves the
original PR looking untouched, and gives the reviewer two heads to choose
between. Only start a new branch when the task asks for new work.

## Commit AND push the branch

Commit, then **push that branch to origin**. Do not open a PR - that is the last
phase's job (and for a rework there is already one).

Pushing is not optional. **Every phase runs in its own fresh workspace with its
own clone**, so nothing on this filesystem survives into the next phase; only
your artifact does. A branch left local is destroyed when this phase ends, the
verify phase would check the default branch while believing it checked your work,
and the final phase would have nothing to open a PR from.

**Record in your artifact, exactly:** the branch name and the full commit SHA you
pushed. The next phase checks out that SHA by name. If it is missing or wrong,
verification silently runs against the wrong code.

## Output

What you changed and why, the full diff, which hops you touched, and what you
deliberately did not do.
