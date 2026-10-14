# Confirm the fix closed what you found

$ARGUMENTS

**Skills:** `testing`, `error-handling`, `security` and `architecture` are installed in this workspace as context, because codex has no Skill tool. Read and apply them when you judge whether each fix closed its finding.

**Say which agent you are.** This phase is declared on codex so that a
different model family from the implementer reviews the change, with claude as
its `fallback_agent` for when codex's provider refuses the request (a content
filter, a spent quota, no capacity). Put the line `Verifier: <provider>/<model>`
in your report, after whatever lines this file requires first, naming the
agent you actually are, not the one this file assumes. If you are not codex, add one sentence saying this review
ran on the fallback agent and was therefore NOT cross-family.

## Which round this is

**Round 2 of 2.** **This is the final round**: there is no third. This prompt re-verifies after each of up to two fix
rounds. This round's fix report is **`artifacts/input/fix_2/fix.md`** (flat
alias `artifacts/input/fix_2.md`); the verdict that fix round acted on is
`artifacts/input/reverify/reverify.md`. Read the fix report first. It says what the previous phase did about
the defects still open. Write `Round: 2 of 2` as your report's second line.

## Check out the candidate you will certify

**You are in a fresh workspace with a fresh clone of the default branch**, so
nothing you are about to certify is on disk yet. Read the branch, the first-pass
verified SHA and the final pushed SHA from the artifacts, and decide which SHA
is the candidate:

- If `fix.md` says no change was made, the candidate is the SHA the verdict
  that fix round acted on named (the first-pass verified SHA in round 1).
- Otherwise the candidate is the full SHA `fix.md` says it pushed.

Then run:

```
git fetch origin <branch>
git rev-parse origin/<branch>
git checkout --recurse-submodules <candidate-sha>
git rev-parse HEAD
```

The remote head and `HEAD` must both equal the candidate SHA. **If either SHA
is absent from the reports or differs from the candidate, output BLOCKED** and
say which value disagreed: the branch moved after the fix, or a report named a
head that is not there, and either way the thing on origin is not the thing you
would be certifying.

For a repair, read `git diff <first-pass-verified-sha>...<candidate-sha>` and
the resulting code. **Never certify from `fix.md` alone** - it is the claim, not
the evidence.

## Evidence precheck: classify before you block

Run this right after the checkout above, before the gates. It sorts every
problem with the evidence into one of four classes, and **only one of them,
`REPAIRABLE`, can make this review BLOCKED**. Under v3, repair rounds kept
going to things a fix phase in a workspace cannot change: a head CI never ran
on, a check that fails in files the PR did not touch, a registry rate limit,
a package missing from the CI matrix, and Docker or database evidence that no
workspace can produce. Each of those cost a full fix plus re-verify and came
back still open. The precheck hands them to `finalize_pr` instead, which
keeps the PR a draft and posts them for whoever can act.

| Class | What it is | Who closes it | Repair round? |
|---|---|---|---|
| `REPAIRABLE` | a fix phase can close it by changing and pushing this branch | the next `fix` | yes: it is BLOCKING |
| `FLAKE/INFRA` | a red or missing check whose cause is outside this diff | one rerun, by `finalize_pr` or the orchestrator | never |
| `ORCHESTRATOR_EVIDENCE` | evidence that needs Docker, a database or a real store, which this workspace lacks | the orchestrator, running the exact command you give | never |
| `CI_GAP` | CI cannot see this PR until something outside the branch changes: the PR's base, or `.github/workflows/`, which a workspace credential cannot push | the orchestrator, with the command or patch you give | never |

**A handoff never makes a PR ready.** `finalize_pr` leaves a PR with any open
handoff as a draft, so putting a real defect in a handoff class does not ship
it. It parks the defect in front of a person who has less context than you
do. **A class whose required evidence (below) you cannot show is
`REPAIRABLE`.**

### 1. The PR's head, base and checks

```
gh pr view <n> --json headRefOid,mergeStateStatus,baseRefName,statusCheckRollup
gh repo view --json defaultBranchRef --jq .defaultBranchRef.name
```

`headRefOid` must equal `git rev-parse HEAD`. If it does not, stop as the
checkout section says. Then:

- **`mergeStateStatus` is `DIRTY`** (it conflicts with its base, so
  `pull_request` CI never ran on it): `REPAIRABLE`, "merge main first". The fix
  is `git fetch origin && git merge origin/<base>`, resolve, push. That is
  never a rebase and never a force push. Do not wait on CI for this head, as
  nothing is coming.
- **`baseRefName` is not the default branch** (for example, a PR stacked on a
  branch that has since merged): `CI_GAP`, "retarget". The command is
  `gh pr edit <n> --base <default>`. CI that ran against the old base says
  nothing about the merge into the default branch.
- **`statusCheckRollup` is empty**, for neither reason above: re-read it once
  after your gates have run, since they take minutes and CI may only have
  been queued. If it is still empty, run `gh run list --commit <sha> --json
  name,status,conclusion,event`. Report `CI never ran: <reason>`, with the
  reason taken from that output and not guessed. Classify it `FLAKE/INFRA`
  when the cause is the platform (Actions outage, a run that never started)
  and `CI_GAP` when the cause is configuration outside the branch. Every check
  that CI would have settled is then unsettled. Say so; never call it passed.

### 2. Every new or changed test file has a CI job that runs it

```
git diff --name-only --diff-filter=AM origin/<base>...HEAD
```

For every test file in that list, name the CI job that runs it. Read the
job's command in `.github/workflows/` (read it, never edit it) and show the
file's progress line in that job's log on this SHA, as the CI section below
describes. A test that no PR-gating job collects is a blocking finding
(`no CI job runs <file>`). Typical causes are a package missing from a job's
matrix, a path no job's command reaches, or a marker no job selects. Classify
it by where the fix lives:

- **in the branch** (add the marker, move the file under a collected path,
  add it to the package's own test config): `REPAIRABLE`.
- **in `.github/workflows/`**: `CI_GAP`. The workspace credential refuses any
  push that touches that directory, so a fix round cannot close it. Write the
  change as a unified diff to `artifacts/output/ci-coverage.patch` and name it
  in the handoff.

This check and the checks treatment in
`workflows/evals/verify-pinned-codex-checks/` ask the same question.
`EXPERIMENT.md` counts these findings separately so the two can be told apart.

### 3. A failing check whose cause is outside this diff

For every check that failed on this SHA, read the failing step, not the
summary:

```
gh run view --job <job-id> --log-failed | tail -n 80
git diff --name-only origin/<base>...HEAD
```

It is `FLAKE/INFRA` only when **all** of these hold, and you show each one:

1. The failure is in a step, file or test that this PR's diff does not
   contain. Name the files in the failure (the test file, the traceback
   frames, the build target).
2. None of those files imports, builds or reads anything in the diff. A test
   the PR did not edit that exercises code the PR did edit is the PR's
   failure, and is `REPAIRABLE`.
3. The failure matches a known flake or infrastructure class (see
   `.claude/skills/devops/agent_ci_triage.md` step 4: apt or DNS failures,
   corepack/pnpm fetch, `UND_ERR_SOCKET`, registry 5xx or rate limit), or the
   same check fails the same way on the base branch.
4. It has not already failed on this same step after a rerun. **Failing twice
   on the same step is a defect, not a flake.** Report it as a defect on the
   base, still never as a repair round on this PR: this branch did not cause
   it and cannot fix it. The PR stays a draft until the base is green.

Request one rerun yourself: `gh run rerun <run-id> --failed`. This workspace's
GitHub App token is documented as `Actions: Read`, so a refusal (HTTP 403,
"Resource not accessible by integration") is expected and is not an error. Put
the command and the refusal, verbatim, in the handoff. If the rerun is
accepted, wait on it as the CI section below says (`timeout 25m gh pr checks
<n> --watch --interval 60`) and read it again. Green on this SHA closes the
item.

### 4. Evidence this workspace cannot produce

A check whose evidence needs Docker, a database, a real event store or object
store, or any other service this workspace does not have, and which CI does
not settle on this SHA (read as the CI section below says), is
`ORCHESTRATOR_EVIDENCE`. Give:

- the exact command, run from the repository root at this SHA, including any
  `just` recipe or compose profile it needs;
- what output proves it: the test count, the line, the exit code;
- the changed files it covers.

It is never `BLOCKING` and never a repair round, because a fix phase in a
workspace cannot run it any more than you can. Code you *can* run here,
because it needs no such service, is not this class: run it.

### What this changes in the rules below

The CI section below is the same as in sdlc-implement-v3, and two of its
rules give way to this precheck:

- "**Failed on this SHA:** it IS a blocker" does not apply to a failure you
  showed above to be `FLAKE/INFRA`. That failure is a handoff.
- "Without either, it IS a blocker", for a job that is skipped by design but
  covers changed code, does not apply when the missing evidence needs Docker,
  a database or a real store. That is `ORCHESTRATOR_EVIDENCE`.

Everything else in that section stands, including that a pass on an older
head proves nothing.

### Write it down

Your report carries exactly one line of this form, counting the items under
each class:

```
Precheck: REPAIRABLE=<n> FLAKE_INFRA=<n> ORCHESTRATOR_EVIDENCE=<n> CI_GAP=<n>
```

It also carries a `## Handed to the orchestrator` section. That section holds
a table with one row per open non-`REPAIRABLE` item, or the single word
`None.`:

| Class | Item | Exact command or patch | What closes it |
|---|---|---|---|

Every `REPAIRABLE` item also goes under BLOCKING, written as the instruction
a fix phase can act on (see below). Your verdict is `blocked` if and only if
at least one `REPAIRABLE` item is open. When every open item is a handoff, the
verdict is `certified`: there is nothing left for a repair round to do.
`finalize_pr` reads the handoff table and keeps the PR a draft until those
items close.

In a re-verification, carry forward every handoff in the report the fix
round acted on, and run the precheck again on the candidate SHA. A fix push
starts new CI, so a flake may have cleared, and a handoff that is now closed
leaves the table, with the evidence that closed it.

## If the fix phase changed nothing, say so quickly

A round whose predecessor CERTIFIED never reaches you: the engine reads the
`review_verdict` below and skips the remaining rounds itself.

If `fix.md` reports that the first pass certified the change and no edit was
made, the checkout above has already confirmed it: the remote head is still the
SHA the first pass reviewed. Certify on that, and do not re-run the whole
review. The work was already verified once by a separate model; repeating it
costs a second full pass to learn what you already know.

This is the common case and it must be cheap.

## Otherwise, check the delta, not the world

Your scope is narrow on purpose:

1. **Does the fix actually close each defect the first pass named?** Read the
   code, not the report. A report saying "fixed the regex" is not evidence the
   regex is right.
2. **Did the fix break anything that was previously working?** A targeted edit
   made under time pressure at the end of a run is exactly where a regression
   gets introduced. Check the blast radius of what changed.
3. **Is every test the fix added able to fail?** `fix.md` must name the mutation
   and the failure it produced. If it does not, or if the mutation looks like it
   would not have exercised the assertion, that is a blocking defect - a test
   that asserts nothing is worse than no test, because it will be trusted.

Do NOT re-review the parts of the change the first pass already certified. That
work is done and re-doing it is how a second pass costs as much as the first.

A blocker from `verify.md` that is a check this workspace cannot run is closed
or kept by CI's result on the candidate SHA, as the next section says. That is
not moving the goalposts: it is the same check, read where it actually ran.

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

## A UI change carries its screenshots to the head you certify

If the change touches `apps/syn-dashboard-ui/` or another UI app, `verify.md`
must have a `## Screenshots` section: screenshots of every affected route at
1280x800 and 390x844, each looked at and judged, as its "A UI change is
verified by looking at it" section requires. If it has none, that is a blocking
defect the first pass should have caught, and it stays open until a pass takes
them.

If the fix touched UI files, re-take the screenshots for the routes it affects
with the recipe in `verify.md`'s section (build, serve, then
`node /workspace/repos/syntropic137/apps/syn-dashboard-ui/scripts/screenshot.mjs <url> /workspace/artifacts/output/<route>-<viewport>.png --viewport <WxH>`,
the same absolute path for `apps/syn-docs/`, which has no script of its own),
open each PNG and look at it. If it did not, the first pass's screenshots still
describe the candidate. Their PNGs are under `artifacts/input/<phase-id>/`
byte-for-byte (#990, fixed in #1652): check each starts with `89 50 4e 47` and
opens before relying on it, but the table is still what reaches the PR.

Either way, copy the `## Screenshots` section into your report, replacing each
row you re-took, so that it describes the SHA you certify. `finalize_pr` reads
your report, not `verify.md`, and carries that section into the PR body.

## Be specific about what would make it deliverable

If you find a blocking defect, the next fix round - or, in round 2, whoever
picks up the draft - has only your report to work from. So write it as an
instruction rather than an observation:

- name the file and line
- state what is wrong in one sentence
- state what would close it

"The tests are insufficient" strands the work. "`test_cancel_isolation` builds
one execution, so it cannot fail for the reason #1311 exists; it needs a second
concurrent execution and an assertion that its runtime state is untouched" lets
the next pass finish in one edit.

## Do not move the goalposts

The first pass set the bar. If the fix met it, certify - even if you would
personally have asked for more. Raising the standard on the second pass means no
change can ever pass two reviewers with different tastes, and the run dies for a
reason that is about reviewers rather than about the code.

A genuinely NEW blocking defect introduced by the fix is different, and is in
scope. Say explicitly which it is: "the fix introduced X" or "the first pass
should have caught Y".

## Write to `artifacts/output/reverify.md`

**This phase declares a markdown output artifact, so a run that writes nothing
under `artifacts/output/` FAILS.** Write the file before you finish.

1. **CERTIFIED** or **BLOCKED**, as the first line, in one word.
   Then `Round: N of 2` on the second line. If round 2 is BLOCKED, the third
   line is `Repair bound reached: 2 of 2 rounds used, findings still open.` -
   the run stops here and must not read as though it ran out of anything else.
   Only `REPAIRABLE` items make a round BLOCKED. An open handoff does not.
2. **The branch and the full commit SHA you certified** - or, if BLOCKED, the
   one you checked out and refused - with the `git rev-parse origin/<branch>`
   and `git rev-parse HEAD` output that proves you checked it out. The phase
   after you opens a PR only for that exact SHA, and an abbreviated or absent
   one leaves it nothing to compare against. On a BLOCKED verdict the future
   pass that picks this up needs to know which head your findings describe.
3. **Each blocking defect from `verify.md` and earlier `reverify` reports** -
   every one, not only the ones `fix.md` discusses - and whether it is now closed, with the `file:line` you
   checked.
4. **Any regression** the fix introduced.
5. **The mutation evidence** for tests the fix touched, and whether you believe
   it.
6. If BLOCKED: **what would close it**, file and line and assertion.
7. **The `Precheck:` line and `## Handed to the orchestrator`**, as the
   evidence precheck says. Handoffs carried from earlier reports are included.
8. **`## Screenshots`**, if the change touches a UI app: the table from
   `verify.md`, with the rows you re-took replaced, as the section above says.

## Report the verdict to the engine, not only in prose

Your `TASK_RESULT` block MUST carry `"review_verdict"`, exactly `"certified"`
or `"blocked"`, matching your first line. The engine reads that key, and only
that key, to decide what runs next: `certified` skips every remaining repair
round and goes straight to `finalize_pr`; `blocked` runs the next round, or
ends the run with **unresolved findings** once the rounds are spent. This phase
declares `requires_verdict`, so a missing or misspelled verdict FAILS the phase
("verify produced no verdict") and the review you did is not acted on; it is
never read as certified.

`review_verdict` is not `success`. A BLOCKED review you completed is a
successful phase: write `"success": true, "review_verdict": "blocked"`.

A pull request is marked ready if and only if the last round run certifies.

`--recurse-submodules` is required, not optional. Without it `git checkout`
moves the superproject but leaves submodule working directories where they
were, so `git status --porcelain` reports every submodule whose gitlink
differs as modified. The unpushed-work guard treats that as unsaved authored
work and fails the phase AFTER the review is complete but BEFORE it is stored.
That discarded a 21-minute codex review on exec-5a22616362bd (#1499).
