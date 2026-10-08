# Verify the change independently

$ARGUMENTS

**Skills:** `testing`, `error-handling`, `architecture` and `software-complexity` are installed in this workspace as context, because codex has no Skill tool. Read and apply them when you judge the tests, the failure paths, the boundaries and the complexity of the change.

The implementation report is at `artifacts/input/prepare.md`. Your job is to
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

## Report the verdict to the engine, not only in prose

Read this before you run anything long: it is the one part of this phase the
engine reads, and a run that ends before you reach the bottom of this prompt
must still have obeyed it.

Your `TASK_RESULT` block MUST carry `"review_verdict"`, exactly `"certified"`
or `"blocked"`, matching the first line of your report. The engine reads that
key, and only that key, to decide what runs next: `certified` skips every
repair round and goes straight to `finalize_pr`; `blocked` runs the first
repair round (`fix`, then `reverify`). This phase declares `requires_verdict`,
so a missing or misspelled verdict FAILS the phase ("verify produced no
verdict") and the review you did is not acted on; it is never read as
certified.

`review_verdict` is not `success`. A BLOCKED review you completed is a
successful phase: write `"success": true, "review_verdict": "blocked"`.

Your report's first line is exactly `CERTIFIED` or `BLOCKED`, and its second
line is exactly `Round: 0 of 3`: no repair round has run yet. `finalize_pr`
reads this report as the final one when you certify, and refuses a report
whose first two lines are anything else.

## First: check out the code you are verifying

**You are in a fresh workspace with a fresh clone of the default branch.** The
implementation is not here yet. Before anything else:

```
git fetch origin <branch-from-the-artifact>
git checkout --recurse-submodules <the-exact-commit-SHA-from-the-artifact>
git rev-parse HEAD          # must equal that SHA
```

Paste that `rev-parse` output. If it does not match, stop and report it: every
result after this point would describe the wrong code, and a green run against
the wrong tree is worse than a red one because it certifies nothing while looking
like proof.

## Run the gates

**The gates belong to the repository you are verifying, not to this prompt.**
This workflow runs against any repository, and a command that is the gate in
one of them does not exist in another: a run on a repository with no
`justfile` could not certify anything while this prompt named one (PC-129).
So find the gates in this order, and stop at the first that answers:

1. **Declared.** The repository's `AGENTS.md` (or `CLAUDE.md`, if it has no
   `AGENTS.md`) has a `## Verification gates` section. Its first fenced code
   block lists the gate commands, one per line, run from the repository root.
   Run every one of them, in order. Read the rest of the section too: it is
   where the repository says what its gates cannot do in this workspace.
2. **Not declared.** Find what the repository itself treats as its gate and
   run that: the commands its pull-request CI runs (`.github/workflows/`),
   then its task runner (`justfile`, `Makefile`, `package.json` scripts), then
   any test command its `AGENTS.md`, `CLAUDE.md` or `README` names in prose.
   Run the narrowest set that covers what this change touches.
3. **None found.** Say so. A repository with no gate has nothing to be green
   against; that is a fact to report, not a failure to invent and not a pass
   to claim. Run the tests the change itself added or touched.

Whichever case applied, your report names it, and names the file and line
each command came from. A gate whose provenance is not written down cannot be
checked by the next phase.

Run them with the workspace's write locations redirected first:

```
mkdir -p /workspace/.tmp /workspace/.cache
export TMPDIR=/workspace/.tmp XDG_CACHE_HOME=/workspace/.cache UV_CACHE_DIR=/workspace/.cache/uv
```

Paste the final lines of each gate. If any is not green, that is the finding
and you should stop and report it rather than working around it.

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

**A gate that needs a binary this workspace lacks did not run.** The image
ships `just`, `uv`, `node`, `gh` and `rustup`, and nothing else. A gate that
fails on a missing binary has told you nothing about the change: report it as
not run, never as passed, and never swap in a command the repository did not
choose. A line the gate itself prints as `NOT RUN` is the same thing. CI on the
same head SHA settles it, as the section after this one says.

**Run the whole gate, not the sub-commands you think it contains.** A change can
pass every test, typecheck and build and still fail on something none of them
touch. A CLI flag added in syntropic137 drifted a generated docs page and
failed `codegen-check`, a real PR-gating job, while every direct test passed.

Run `git status --porcelain` before and after. Verification commands in this
repository have mutated tracked files; if the tree changed, report it.

## A check this workspace cannot run is settled by CI on the same head SHA

Some checks cannot run here at all: a gate that needs a binary this workspace
lacks, or a test the gate itself reports as `NOT RUN` (in syntropic137,
today, the docker-backed fitness tests). "Not run here" is not a pass, and
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
  `github.base_ref == 'release'`, so a PR into `main` never gets it. Then
  decide whether the job covers this PR: compare the test paths in the job's
  command with `git diff --name-only origin/main...HEAD`. The job covers this
  PR when a changed file is one of those tests or code they exercise.
  - **It covers nothing this PR changes:** that check is NOT a blocker, since
    no CI result is coming to wait for, and NOT a pass, since nothing ran it.
    List it in the verdict under a heading `Unverified by design`, one line per
    check: the job name, the check it would have run, and the skip reason
    quoted from the `if:`. Carry the same lines into the PR body under the same
    heading, so a reviewer sees what was never run.
  - **It covers code or tests this PR changes:** the skip does not settle it,
    because this PR changes the behaviour that job exists to check. Produce
    independent evidence on this head SHA: run those tests here if this
    workspace can, or cite another CI job that ran them on this SHA, read as
    above. Without either, it IS a blocker: put it under BLOCKING with the job
    name, the changed files it covers, and the run that would close it.
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

## A UI change is verified by looking at it

If the diff touches `apps/syn-dashboard-ui/` or another UI app (today
`apps/syn-docs/`), you verify it with screenshots, not by reading JSX. The
owner's rule is that a UI PR does not come back to a human to be looked at; you
are the one who looks. **A UI change verified without screenshots is
BLOCKING**, however good the code reads.

Build and serve the production build, then screenshot every route the diff
affects - a changed page, and every page that renders a changed component -
at both viewports:

```
REPO=/workspace/repos/syntropic137
SHOT="$REPO/apps/syn-dashboard-ui/scripts/screenshot.mjs"

# apps/syn-dashboard-ui
cd "$REPO/apps/syn-dashboard-ui"
pnpm install --frozen-lockfile && pnpm build
pnpm preview --port 4173 --strictPort &
URL=http://localhost:4173

# apps/syn-docs instead (Next.js; `next start` exits if the port is taken)
cd "$REPO/apps/syn-docs"
pnpm install --frozen-lockfile && pnpm build
pnpm start -p 4174 &
URL=http://localhost:4174

# then, for each affected <route>, from any directory:
node "$SHOT" "$URL/<route>" \
  /workspace/artifacts/output/<route>-1280x800.png --viewport 1280x800
node "$SHOT" "$URL/<route>" \
  /workspace/artifacts/output/<route>-390x844.png --viewport 390x844
```

There is one screenshot script and it lives in the dashboard app; `syn-docs`
has none, so always call it by the absolute path above, never as a relative
`scripts/screenshot.mjs`. `$SHOT` uses the Playwright and headless Chromium baked into
this image, so nothing needs installing; `apps/syn-dashboard-ui/README.md` ("Screenshots for
UI verification") says what it prints. It exits 1 on an HTTP error status, and
that is a failed screenshot, not a picture of the page. Name each file
`<route>-<viewport>.png`, with `root` for `/` and `-` for each further `/`
(`executions-1280x800.png`, `executions-abc-390x844.png`). Write them to
`/workspace/artifacts/output/`, the only place the platform collects; never
commit them.

**The PNG files reach the next phase byte-for-byte.** Artifact collection
keeps binary files intact (#990, fixed in #1652), so a later phase finds them
under `artifacts/input/<phase-id>/`, can check each starts with the PNG magic
bytes `89 50 4e 47`, and can open it. The judgement is still made HERE, in this
workspace, on the files you just wrote: the PR body is built from the
`## Screenshots` table below, not from the files, which is why every row says
in words what the image shows. Do not defer looking to a later phase.

**Then open every PNG and look at it.** You can read image files. A screenshot
nobody looked at is the same as no screenshot. For each one judge: is the
layout broken, does anything overflow or force horizontal scroll at phone
width, is an element the change was meant to add or move missing, is the page
showing an error state where the change should render.

**No API is reachable here, and the dashboard has no fixture or mock-data mode**
(#1647), so pages render their shell - navigation, header, filters, page chrome
- with the data area in its loading state. That is expected and is not a
defect. Do not build a mock layer to get around it. Screenshot what renders and
judge only what the PR changed: a change to layout, navigation, filters or
anything else in the shell is fully checkable; a change that only shows with
data (a table row, a chart, a cost figure) is not, so name it under
`Unverified by design` with the reason, rather than certifying a loading
spinner as proof of it.

Put a `## Screenshots` section in your report with one row per image:

| Path | Viewport | What it shows | Verdict |
|---|---|---|---|

with the screenshot script's output line for each. `finalize_pr` carries that
section into the PR body, so a reviewer sees what was looked at without
opening anything.

## Write to `artifacts/output/verify.md`

**This phase declares a markdown output artifact, so a run that writes
nothing under `artifacts/output/` FAILS - after the work is done, and the
work is lost with the workspace.** Write the file before you finish, even
if the outcome was a refusal: a refusal is a deliverable and is often the
most valuable one.

The verdict, the gate output, the mutation results, and the exact head you verified.
A verdict: is the change correct and complete, or not. The first two lines are
the verdict and `Round: 0 of 3`, as the verdict section at the top says. Which
gates you ran, where each came from (declared, found, or none), and their output, each
mutation and its result, and anything you could not verify. If you found a
defect, say exactly what and where; do not fix it silently.

**Name the branch and the full commit SHA you verified**, together with the
`git rev-parse HEAD` output above. The `fix` phase starts in a fresh clone of
the default branch and has only your report to learn the branch from; without
the name it cannot fetch what you reviewed, and without the full SHA it cannot
tell whether what it fetched is still it.

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

## A defect you find is repaired, not fatal

A `fix` phase runs after you, reads this report, and repairs what you name. Then
a second verification pass checks the repair. So finding a defect no longer ends
the run and discards the work - it starts the repair.

This changes how to write the finding, not how hard to look. **Write each
blocking defect as an instruction a fix phase can act on**, not as a verdict:

- name the file and line
- state what is wrong in one sentence
- state what would close it

"The tests are insufficient" strands the work. "`test_cancel_isolation` builds
one execution, so it cannot fail for the reason #1311 exists; it needs a second
concurrent execution and an assertion that its runtime state is untouched" gets
fixed in one edit.

Two things not to do with this:

- **Do not lower the bar** because a repair is available. A defect you wave
  through is one the second pass inherits with less budget to catch it.
- **Do not widen it either.** The fix phase is scoped to exactly what you name,
  and the run has already spent most of its budget reaching you. Findings that
  are genuinely optional belong under a heading that says so, clearly separated
  from what blocks delivery.

Mark plainly which findings block and which do not. The fix phase will treat
everything you call blocking as required work.

## Report completion to the workflow

Your task in this phase is to deliver an honest verification report, not to
make the candidate pass. If you can identify the candidate and write
`artifacts/output/verify.md`, end with `TASK_RESULT success=true` and the
`review_verdict` the section at the top requires, even when the candidate is
BLOCKED.

This includes a normal code, test, or design defect; a failing gate; and an
environment limitation that prevents only part of verification, such as an
unavailable database. Put each such item under a `BLOCKING` heading with the
file and line or affected command, the root cause, the exact action required,
and what would prove it closed. The one exception is a check whose CI job is
skipped by design for this PR and covers nothing this PR changes, proven from
the job's `if:` and the diff as the CI section above describes: it is never
`BLOCKING`, even when this workspace also lacks what it needs, such as a
database. List it under `Unverified by design` instead, and carry that heading
into the PR body. A skipped job that covers code or tests this PR changes is
not that exception: without independent evidence it is `BLOCKING`. `success=true` means the verification report
was delivered so the `fix` phase can run; it does not mean the candidate was
certified.

Use `TASK_RESULT success=false` only when verification itself could not run at
all: for example, the implementation artifact is missing or unreadable, the
exact branch and SHA cannot be fetched or checked out, or no verification
artifact can be written. Do not use `success=false` merely because the
candidate failed or because one requested check could not run.

A draft PR for this branch already exists (the implement phase opened it). Do
not create, edit, comment on, or mark ready any pull request: your verdict
reaches it through `finalize_pr`, the only phase allowed to change its state.

`--recurse-submodules` is required, not optional. Without it `git checkout`
moves the superproject but leaves submodule working directories where they
were, so `git status --porcelain` reports every submodule whose gitlink
differs as modified. The unpushed-work guard treats that as unsaved authored
work and fails the phase AFTER the review is complete but BEFORE it is stored.
That discarded a 21-minute codex review on exec-5a22616362bd (#1499).
