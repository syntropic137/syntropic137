# Confirm the fix closed what you found

$ARGUMENTS

## Which round this is

**Round 1 of 3.** This prompt re-verifies after each of up to three fix
rounds. This round's fix report is **`artifacts/input/fix/fix.md`** (flat
alias `artifacts/input/fix.md`); the verdict that fix round acted on is
`artifacts/input/verify/verify.md`. Read the fix report first. It says what the previous phase did about
the defects still open. Write `Round: 1 of 3` as your report's second line.

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

## Be specific about what would make it deliverable

If you find a blocking defect, the next fix round - or, in round 3, whoever
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
   Then `Round: N of 3` on the second line. If round 3 is BLOCKED, the third
   line is `Repair bound reached: 3 of 3 rounds used, findings still open.` -
   the run stops here and must not read as though it ran out of anything else.
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

## Report the verdict to the engine, not only in prose

Your `TASK_RESULT` block MUST carry `"review_verdict"`, exactly `"certified"`
or `"blocked"`, matching your first line. The engine reads that key, and only
that key, to decide what runs next: `certified` skips every remaining repair
round and goes straight to `finalize_pr`; `blocked` runs the next round, or
ends the run with **unresolved findings** once the rounds are spent. A missing
or misspelled verdict is read as no verdict, which never skips a round and
never counts as certified.

`review_verdict` is not `success`. A BLOCKED review you completed is a
successful phase: write `"success": true, "review_verdict": "blocked"`.

A pull request is marked ready if and only if the last round run certifies.

`--recurse-submodules` is required, not optional. Without it `git checkout`
moves the superproject but leaves submodule working directories where they
were, so `git status --porcelain` reports every submodule whose gitlink
differs as modified. The unpushed-work guard treats that as unsaved authored
work and fails the phase AFTER the review is complete but BEFORE it is stored.
That discarded a 21-minute codex review on exec-5a22616362bd (#1499).
