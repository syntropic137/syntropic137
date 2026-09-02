# Verify the change independently

$ARGUMENTS

The implementation report is at `artifacts/input/implement.md`. Your job is to
find out whether that change is actually correct, not to confirm that it is.

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

This phase exists because a phase that makes a change and then checks it will
shortchange the checking: the change feels like the deliverable, and the check
feels like paperwork. You did not write this code. Treat it as suspect.

## First: check out the code you are verifying

**You are in a fresh workspace with a fresh clone of the default branch.** The
implementation is not here yet. Before anything else:

```
git fetch origin <branch-from-the-artifact>
git checkout <the-exact-commit-SHA-from-the-artifact>
git rev-parse HEAD          # must equal that SHA
```

Paste that `rev-parse` output. If it does not match, stop and report it: every
result after this point would describe the wrong code, and a green run against
the wrong tree is worse than a red one because it certifies nothing while looking
like proof.

## Run the gates

Run `just qa-ci`. Paste its final lines. If it is not green, that is the finding
and you should stop and report it rather than working around it.

**Run the whole gate, not the sub-commands you think it contains.** A change can
pass every test, typecheck and build and still fail CI on something none of them
touch. A CLI flag added in this repository drifted a generated docs page and
failed `codegen-check`, a real PR-gating job, while every direct test passed. If
`just qa-ci` cannot run here, name the gates it would have run and run each one,
rather than substituting the two you happen to know.

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

## Ask which production input shapes the fixtures cannot construct

This is the question that decides whether the tests are worth anything, and it is
the one most often skipped. Mutation testing proves a test is not vacuous. It
cannot prove the fix is correct, because mutating the code can never surface a
layer the fixture never reaches.

So for every new test, name the shapes of real input it does NOT build, and then
build them:

- Values the WRITE path can actually emit. Read the producer, not the consumer. A
  fixture seeding a field the failure path never records certifies a case that
  cannot occur; a test in this repository asserted on a session with tokens
  recorded, when the code that completes a failed session records nothing at all.
- Rows that arrive alone. A start with no completion, a completion with no start,
  a truncated stream. Pairs are the easy case and rarely the broken one.
- Values a projection or converter REWRITES before the code under test sees them.
  A fixture built by hand skips that rewrite, so a defect living in it is
  invisible to every mutation you try.
- Inputs a user would plausibly type that the author did not imagine. For a path
  or an identifier that means absolute paths, trailing separators, dots, query
  strings, whitespace, and platform-specific spellings.
- Duplicates and replays. An event store can deliver the same row twice.

Where the real conversion is reachable, drive the fixture THROUGH it rather than
constructing the object directly. State in your report which shapes you added and
which you decided were out of scope, with the reason.

### Prefer an invariant to a case list

A test per case can be satisfied by encoding the wrong answer for that case. It
has happened here: a fix was asked to handle a missing identifier, considered it,
chose behaviour that produces an impossible result, and then wrote a test
asserting that result was correct. The case was covered and the defect was
pinned in place by the assertion defending it.

So where the change has a property that must hold for EVERY input, assert the
property, not the examples. `call_count >= success_count + error_count` cannot be
satisfied by blessing one wrong output, while a test named for the empty-id case
can. Find the invariant first; fall back to cases only where no invariant exists.

If you find yourself writing an assertion that documents surprising behaviour
rather than requiring correct behaviour, stop and say so in your report. That is
a finding, not a test.

### Test the transition, not the end state

The commonest way a required case gets skipped is a test NAMED for it that
starts where the case has already finished. It reads as coverage in the file
listing and proves nothing.

Seen here, on a run that was explicitly asked for these shapes:

- a test called "stops when terminal" that MOUNTS already-terminal. It never
  ran, never polled, never received the terminal response, so it cannot show
  that anything stopped.
- a test for tab visibility that set the tab hidden and never dispatched
  `visibilitychange`, and never returned to visible, so neither the pause nor
  the resume path executed.

Both would pass against code that handles the transition wrongly.

So when a case is a CHANGE of state, the test must start before the change,
cause it, and assert on what happens after. If your test's setup already
contains the condition you were asked to verify, you are testing the aftermath.
Name that in your report rather than counting it as covered.

The check to run on your own test list: for each required shape, can you point
at the line where the state CHANGES? If not, that shape is not covered, however
the test is named.

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
