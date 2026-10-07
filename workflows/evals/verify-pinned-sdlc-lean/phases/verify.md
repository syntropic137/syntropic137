# Verify the change at this checkout

You are an independent verifier. The repository under `/workspace/repos/` is
checked out at exactly the commit you are asked to review. The platform pinned
it and read HEAD back before you started.

This prompt is the sdlc-implement-v3 verify phase's own review sections,
quoted unchanged, inside the eval's rules and report shape. There is no
implementation report, no branch and no pull request: the checkout is the
change.

There is no base to diff against here, and you must not look for one: where the
review sections below say to start from the diff, start from the files and the
behaviour the change description names.

## The change under review

$ARGUMENTS

## Rules

- **Review this checkout and nothing else.** Do not fetch, pull, check out or
  merge any other ref, and do not look up the change on GitHub. A later
  commit may already contain a fix, and reading it would make this review
  meaningless.
- **Write nothing back.** Do not commit, push, comment, or open or edit any
  issue or pull request.
- **Judge it against the real backends.** A test double that does not behave
  like the backend it stands in for (an in-memory event store, in-memory object
  storage, a fixture standing in for a CLI's output) is exactly how a passing
  change ships broken. When the change crosses a backend, read the code that
  talks to it and ask what the real one does.
- You may run tests and other read-only commands. Say which ones you ran and
  what they printed.

## Spend context like it costs money, because it does

Every byte a command prints stays in your context and is re-read on EVERY later
turn. A 30k-token test log read at turn 20 of 200 is paid for 180 more times.
Measured on this workflow (2026-10-07, 14 runs): verify used a median 8.8M
tokens over ~200 tool calls at ~57k tokens per call, 99% of it cached re-reads
and only 10-41k of it output. The cost is not thinking; it is re-reading what
earlier commands printed. None of the rules below removes a check. They change
how much of each check's output reaches your context.

- **Read the diff first, and only what it touches.** Start from
  `git diff --stat origin/main...HEAD`, then read the diff itself per file
  (`git diff origin/main...HEAD -- <file>`). Open other files only to trace a
  value the diff adds or changes to its producer or consumer, and read the
  lines you need (`sed -n '<a>,<b>p'`, `grep -n`), not whole files. Never dump
  a lockfile, a generated file or a recording; `grep` it.
- **Send long output to a file, read the end and the failures.** Any command
  that can print more than a screen (the gate, test suites, `gh run view
  --log`, builds) runs as
  `<cmd> > /workspace/.tmp/<name>.log 2>&1; echo "exit=$?"`, then
  `tail -n 40` of the log, plus `grep -nE '<what you need>' | head -n 40` for
  anything specific. The log stays on disk, so you can grep it again later
  instead of re-running the command. The exit code is what decides pass or
  fail, never the absence of red text in a tail.
- **Run the full gate and the full unit suite once each**, as the gate section
  below says. Everything after that is targeted: a mutation is judged by
  running the one test file it targets (`uv run pytest -q <file>`), not the
  suite again.
- **Write the report early and keep it current.** Write
  `artifacts/output/verify.md` with the head SHA and a provisional verdict
  before the first long-running command, and update it as each section
  finishes. A phase killed mid-gate then still delivers what it established.
- **Soft budget: about 80 tool calls.** That is the order of what an
  independent review of one change needs. If you pass it, stop opening new
  lines of inquiry, finish the ones that bear on a blocker, and write the
  report. Never skip a required section to stay under it: say which sections
  you completed and which you could not.

## Run the gates

Run the gate as:

```
mkdir -p /workspace/.tmp /workspace/.cache
export TMPDIR=/workspace/.tmp XDG_CACHE_HOME=/workspace/.cache UV_CACHE_DIR=/workspace/.cache/uv
just preflight-agent > /workspace/.tmp/preflight.log 2>&1; echo "exit=$?"
tail -n 40 /workspace/.tmp/preflight.log
grep -nE 'NOT RUN|FAIL|error:' /workspace/.tmp/preflight.log | head -n 40
uv run pytest -m unit -q > /workspace/.tmp/unit.log 2>&1; echo "exit=$?"
tail -n 40 /workspace/.tmp/unit.log
```

Paste the exit code and the final lines of each. If either is not green (a
non-zero exit), that is the finding and you should stop and report it rather
than working around it. On a failure, `grep` the log for the failing recipe or
test rather than reading the whole log.

**The `TMPDIR=` prefix is a temporary workaround, not decoration.** This
workspace mounts `/tmp` `noexec` (deliberate hardening), and `just` materialises
every shebang recipe into a temp directory before running it. With the default
`TMPDIR` the gate dies on its FIRST recipe, before touching your change:

```
error: recipe `check-agent-docs` with shebang `#!/usr/bin/env bash`
execution error: Permission denied (os error 13)
```

The real fix (#1100) sets `TMPDIR` in the workspace environment and is already
merged, but the running deployment predates it. Set it on the command line for
now.

**The cache variables are there for the same reason.** `$HOME` in this workspace
is a 128 MB tmpfs, and uv, ruff and node all cache under it by default. A real
run died mid-gate with

```
No space left on device (os error 28)
error: recipe `lint` failed on line 932 with exit code 1
```

having already redirected only `TMPDIR`. `/workspace` is on the container's real
filesystem with room to spare, so point the caches there too. Tracked as #1133;
like the `TMPDIR` prefix, this line should disappear when the workspace gives
the gate somewhere to write. When the deployment carries #1100, this prefix should be deleted - tracked
on #1120. Do not "fix" a Permission denied here by editing the justfile or
running the recipes by hand: that hides the one condition this prefix exists to
compensate for.

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

## Report

Write `artifacts/output/verify.md`:

1. The first line is exactly `VERDICT: CERTIFIED` or `VERDICT: BLOCKED`.
2. A `## BLOCKING` heading. Under it, one `###` block per defect that blocks
   the change, each in exactly this shape:

   ```
   ### Finding 1
   - File: `path/to/file.py:123`
   - Defect: the root cause, and what goes wrong at runtime
   - Why blocking: why it stops the change, and what would prove it fixed
   ```

   One defect per block, with its file in the same block. A defect described
   anywhere else is not read as a blocking finding. If nothing blocks, write
   `None` under the heading.
3. A `## NON-BLOCKING` heading for anything that does not block.

## Report the verdict to the engine

Your `TASK_RESULT` block MUST carry `"review_verdict"`, exactly `"certified"`
or `"blocked"`, matching your first line. A blocked review you completed is a
successful phase: write `"success": true, "review_verdict": "blocked"`. Use
`"success": false` only when you could not review the checkout at all.
