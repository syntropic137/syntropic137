# Make the change

$ARGUMENTS

The bootstrap report is at `artifacts/input/bootstrap.md`. **If it says the task's
premise is false, stop. Change nothing** and report that. Do not try to salvage
the task by reinterpreting it.

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

## Commit

Commit locally on a new branch. Do not push, do not open a PR - later phases do
that. Never force push, never rebase.

## Output

What you changed and why, the full diff, which hops you touched, and what you
deliberately did not do.
