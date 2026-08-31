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

## Tests

Write tests that would fail without your change. The specific trap in this
codebase: a value written correctly and dropped one hop later, at a constructor
that does not pass it or a serializer that omits it. Those hops pass every test
that checks the objects at either end. So test the thing that CONSUMES your
change, not the object you just edited.

A fixture value must be one that could not have arisen without your change. A
default asserted in its default direction proves nothing.

## Commit AND push the branch

Commit on a new branch, then **push that branch to origin**. Do not open a PR -
that is the last phase's job.

Pushing is not optional. **Every phase runs in its own fresh workspace with its
own clone**, so nothing on this filesystem survives into the next phase; only
your artifact does. A branch left local is destroyed when this phase ends, the
verify phase would check the default branch while believing it checked your work,
and the final phase would have nothing to open a PR from.

Never force push, never rebase.

**Record in your artifact, exactly:** the branch name and the full commit SHA you
pushed. The next phase checks out that SHA by name. If it is missing or wrong,
verification silently runs against the wrong code.

## Output

What you changed and why, the full diff, which hops you touched, and what you
deliberately did not do.
