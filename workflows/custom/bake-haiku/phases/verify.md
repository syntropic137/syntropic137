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
git checkout --recurse-submodules <the-exact-commit-SHA-from-the-artifact>
git rev-parse HEAD          # must equal that SHA
```

**`--recurse-submodules` is required, not optional.** A plain `git checkout`
moves the superproject but leaves every submodule where the default branch put
it, so when the commit under review pins a different gitlink, `git status`
reports ` M lib/<submodule>`. The unpushed-work guard reads that line as unsaved
work and fails the phase after the review is complete but before it is stored,
so the whole review is paid for and lost.

Paste that `rev-parse` output. If it does not match, stop and report it: every
result after this point would describe the wrong code, and a green run against
the wrong tree is worse than a red one because it certifies nothing while looking
like proof.

## Run the gates

Run `just preflight-agent`, then `uv run pytest -m unit -q`. Paste the final
lines of each. If either is not green, that is the finding and you should stop
and report it rather than working around it.

**`preflight-agent`, not `qa-ci`.** This workspace ships `just`, `uv`, `node`
and `rustup` and nothing else, so seven of the gates in `just preflight` cannot
run here at all: `vsa-validate` (no `vsa`), `codegen-check` (no `pnpm`),
`check-submodules`, `check-compose-overlays`, `check-default-workspace-image`,
`check-pinned-image-channels` and `check-compose-images-public`. Attempting
`qa-ci` here fails on the missing binary, not on the change. CI runs those
seven; passing here does not promise a green CI, and if CI fails on one of them
that is a real failure to fix, not an exception to claim.

`preflight-agent` DOES run all of `fitness`: `fitness-check`, CI's thresholds
unchanged (#1498), and `fitness-invariants`, the `pytest ci/fitness` suite CI
runs. The first run in a workspace installs stable Rust and builds `aps` (~6
minutes); later runs reuse both. A `FITNESS NOT RUN:` line means the gate did
not run, which is not a pass: report it, never certify around it. The pytest
summary lists each test skipped as `NOT RUN` for a binary this image lacks
(today, the docker-backed `test_gateway_bind.py`); CI still runs those, and
how to read its result is the section after this one.

**Run the whole gate, not the sub-commands you think it contains.** A change can
pass every test, typecheck and build and still fail on something none of them
touch. A CLI flag added in this repository drifted a generated docs page and
failed `codegen-check`, a real PR-gating job, while every direct test passed.

Run `git status --porcelain` before and after. Verification commands in this
repository have mutated tracked files; if the tree changed, report it.

## A check this workspace cannot run is settled by CI on the same head SHA

Some checks cannot run here at all: today the docker-backed fitness tests,
which `preflight-agent` skips as `NOT RUN`. "Not run here" is not a pass, and
on its own it is not a blocker either. It is a question CI answers for the same
commit, so read CI's answer instead of holding the PR in draft. PRs #1562 and
#1576 each sat BLOCKED on exactly this while CI's Architectural Fitness job had
already run the test green on the same head, and each needed a human to
override the verdict.

**The SHA must match. A green CI run on an older head proves nothing about this
one**, because the code it tested is not the code you are judging. So print both
SHAs, in full, side by side, and compare them before reading any result:

```
git rev-parse HEAD
gh pr list --head <branch> --state all --json number,headRefOid
```

Then find the job that runs the check (`Architectural Fitness` runs
`ci/fitness`) and read its own record, not the PR's summary line:

```
gh pr checks <n> --json name,state,link,workflow
gh run view <run-id> --json headSha,status,conclusion
gh run view --job <job-id> --log | grep -F '<test-file>'
uv run pytest --collect-only -q -m <the job's marker> <test-file>
```

The job's `link` ends in `/actions/runs/<run-id>/job/<job-id>`. Print the run's
`headSha` next to your `git rev-parse HEAD`; both must be the same full SHA.

Then show from that log that the test ran and passed. The repo's pytest config
adds `-q`, so CI prints one progress line per file, not one line per test:
`ci/fitness/infrastructure/test_gateway_bind.py ...   [ 93%]`, one character per
test (a long file wraps onto following lines of bare characters). `.` is a pass;
`s`, `F`, `E`, `x` or `X` is not. Do not look for `<test-file>::` or `PASSED`
lines: that output does not print them. Collecting needs no docker, so count the
file's tests here with the job's own `-m` marker (the log prints the job's pytest
command); the number of dots must equal that count. The same grep also shows any
`SKIPPED [n] <test-file>:...` line from the job's short summary, and there must
be none. A job that is green because it deselected or skipped the test did not
run it, and settles nothing: no progress line for the file, fewer dots than
collected tests, any character other than `.`, or a `SKIPPED` line naming the
file all mean the check was not run.

Then decide, and report the SHA pair, the job link and the log lines whatever
the outcome:

- **Passed on this SHA** (conclusion `success`, one `.` per collected test on the file's progress line, no
  `SKIPPED` line naming it):
  the check is closed. It is not a blocker, and you do not need to run it here.
- **Not finished yet:** wait on it, bounded, rather than blocking:
  `timeout 25m gh pr checks <n> --watch --interval 60`, then read it again as
  above. Do not write your own `sleep` loop. If `timeout` exits 124, CI did not
  finish in time: report the check open and pending, not passed.
- **Failed on this SHA:** it IS a blocker. Put it under BLOCKING with the failing
  job's link and a log excerpt from
  `gh run view --job <job-id> --log-failed | tail -n 80`.
- **Skipped by design for this PR:** CI deliberately does not run the job for
  this PR's base or event. Prove it from the job's `if:` condition in
  `.github/workflows/` (read it, never edit it): for example
  `Python Integration Tests` runs on `pull_request` only when
  `github.base_ref == 'release'`, so a PR into `main` never gets it. That check
  is NOT a blocker, since no CI result is coming to wait for, and NOT a pass,
  since nothing ran it. List it in the verdict under a heading
  `Unverified by design`, one line per check: the job name, the check it would
  have run, and the skip reason quoted from the `if:`. Carry the same lines into
  the PR body under the same heading, so a reviewer sees what was never run.
- **No CI evidence for this SHA** (no PR yet, the PR head is a different SHA, or
  no job ran the test although its `if:` admits this PR): nothing has answered
  the question. Report the check as not run, name it, and never claim CI passed
  it.

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
constructing the object directly. If you describe a fixture as real or verbatim,
it must be byte-for-byte from a recording or a live response. A string derived
from a recording with fields trimmed is NOT verbatim, and saying so overstates
what the test proves. Cite the recording and the line. State in your report which shapes you added and
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

### An invariant can be vacuous too, and here is how to check

Asking for an invariant produces things SHAPED like one. A loop over inputs whose
assertion never mentions the loop variable is a constant assertion wearing a
`for`, and it passes the moment the first item passes.

Seen here on a run that had been asked for exactly this: a test looped over every
content block in a transcript line and then asserted on the LINE's own
`tool_name`, not the block's. One valid block made every later block pass, so the
test could not catch a function that returns after the first block and discards
the rest, which was the actual defect.

Two mechanical checks on any invariant you write:

1. Does the assertion reference the loop variable? If the body would be identical
   with the loop removed, it is not testing each item.
2. Break the property deliberately for the SECOND item only, and confirm the test
   fails. A property that only ever inspects the first item passes this way and
   nothing else will reveal it.

And say what the property IS in words before writing it. "Every raw tool_use
block has a non-null tool name" is checkable. `assert a or b` is not that
property, and the gap between the sentence and the assertion is where these
hide.

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

A verdict: is the change correct and complete, or not. The `preflight-agent` and
unit-test output, each
mutation and its result, and anything you could not verify. If you found a
defect, say exactly what and where; do not fix it silently.

## Judge the design, not only the correctness

A change can be correct and still be the wrong change. Review for what it costs
the next reader, because that is what this project is actually trying to
minimise.

- **Shallow modules.** Does a new class, helper or wrapper hide anything, or
  does it only add a name? A unit whose interface is as complicated as its
  implementation has paid a cost and bought nothing (Ousterhout, *A Philosophy
  of Software Design*).
- **Leaked decisions.** Would changing the implementation force callers to
  change? Then the boundary is wrong, however clean the code looks.
- **Special cases.** Was a branch added to satisfy one caller? Ask whether the
  case could have been made not to exist. Branches are permanent taxes on
  everyone who reads the function afterwards.
- **Duplication of judgement.** Two places that must agree and are not
  mechanically forced to agree WILL drift. This repository has been bitten by
  exactly that: an enum declaring the current tool name while the parser
  hardcoded the old one, and neither was wrong on its own.

Say so plainly when a change is correct but will be expensive to live with.
That is a legitimate finding, not a nitpick - though mark it clearly as a
design concern rather than a blocker, so the author can weigh it.

## Assume the work may be dressed up

Agents under pressure to finish produce work that LOOKS complete: tests that
assert what is already true, a narrower fix that leaves the real defect, a
report stating a number nobody measured. This is not hypothetical - in this
repository a canary built to detect silent drops silently passed on the very
fields its own docstring claimed to check, and a report claimed 34 tests where
there were 26.

So verify the claim against the artifact, not the prose:

- If the report says a test was added, read it. Would it fail if the fix were
  reverted? If you cannot tell, revert the fix and run it.
- If it cites a file and line, open them.
- If it states a count or a timing, run the command and compare.
- If it says a gate passed, check that the gate actually ran.

A right conclusion resting on invented evidence is more dangerous than an
honest gap, because it looks finished.
