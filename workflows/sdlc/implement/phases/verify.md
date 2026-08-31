# Verify the change independently

$ARGUMENTS

The implementation report is at `artifacts/input/implement.md`. Your job is to
find out whether that change is actually correct, not to confirm that it is.

This phase exists because a phase that makes a change and then checks it will
shortchange the checking: the change feels like the deliverable, and the check
feels like paperwork. You did not write this code. Treat it as suspect.

## Run the gates

Run `just qa-ci`. Paste its final lines. If it is not green, that is the finding
and you should stop and report it rather than working around it.

Run `git status --porcelain` before and after. Verification commands in this
repository have mutated tracked files; if the tree changed, report it.

## Attack the tests

For each test the change added, **break the code it guards and confirm that test
fails.** Then restore. Report the mutation and what it killed.

A mutation that misses its target reads exactly like a test that cannot fail, so
confirm the mutation actually applied - check the file really changed before
concluding anything from the test result.

If a test passes against broken code, say so. That is more valuable than a green
run, and it is the specific failure this phase exists to catch.

## Attack the change

Ask what the implementation phase assumed. Trace the value it added or fixed all
the way to whatever consumes it, and check each hop. If the change records
something, confirm the recording is durable rather than in-memory - an event
constructed and never persisted has shipped here before, and every unit test
passed.

## Output

A verdict: is the change correct and complete, or not. The `qa-ci` output, each
mutation and its result, and anything you could not verify. If you found a
defect, say exactly what and where; do not fix it silently.
