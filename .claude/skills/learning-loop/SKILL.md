---
name: learning-loop
description: Use when turning something that happened into something that makes the next run better - "write a retro", "record this paper cut", "this bug escaped verification", "make this an eval", "why do we keep hitting this", "did that change actually help", "scorecard", "what did we learn from that run", "lessons keep getting re-learned". Covers the six-step loop (capture, classify, convert, change, measure, retro), the repo artifact each step produces, and how escaped bugs become eval cases. Do NOT use to design or judge a single workflow experiment (see `workflow-experimentation`, which this loop feeds), to decide where to run work (see `dogfooding`), or to debug one failed execution in the moment.
---

# The learning loop

## Overview

Everything this team has already done is data. Every execution, failed run,
escaped bug and retro is a recorded case that can be replayed against the next
version of a workflow. The owner put it this way on 2026-10-06: "everything that
we've done is basically data, and we can use those as evals to improve", and "we
need the repeatable workflows to rely on, and then use that to compound."

A lesson compounds only if it ends up somewhere the next run reads or a gate
enforces: an eval case, a test, a fitness function, a prompt line, a skill. If it
ends up anywhere else, someone learns it again later at full price. The 2026-10-06
retro is the cautionary example. The same lesson (a test double does not behave
like its backend) cost four separate PRs before anyone wrote it down.

The loop has six steps. Each one produces a specific artifact in this repo, and
a step that produced nothing did not happen:

| Step | Produces |
|---|---|
| 1. Capture | a paper cut or failure record with an execution id and a commit SHA |
| 2. Classify | one category per failure, counted in the retro Scorecard |
| 3. Convert | an eval case for an escaped bug, or an issue with a test or fitness function for a recurring class |
| 4. Change | one variable changed, as a new workflow id or one PR |
| 5. Measure | eval results plus Scorecard numbers, before the change is adopted |
| 6. Retro | `docs/retrospectives/YYYY-MM-DD-<slug>.md` with a Scorecard comparable to the last one |

`workflow-experimentation` covers how to run and judge one change (step 4). This
skill covers where the change comes from and where its result goes.

## Outcomes we are looking for

### Outcome 1: every lesson can be traced to a record

A lesson starts as a stored fact, never as something remembered.

- *Signal:* every paper cut, failure count and escaped bug in a retro cites an
  execution id, a commit SHA, a PR or an issue.
- *Signal:* a retro's timeline comes from GitHub, deployment or command output.
  The 2026-10-04 retro had to correct orchestrator log entries that were stamped
  by hand and ran up to 40 minutes ahead.

### Outcome 2: a lesson ends up where the next run will meet it

- *Signal:* every retro's "What we changed" lists a PR, test, fitness function,
  eval case or prompt or skill edit, and none of its items say only "be more careful".
- *Signal:* a failure class that recurs gets an issue with a proposed test or
  fitness function, and that test eventually lands.

### Outcome 3: escaped bugs become a regression suite for the verifiers

A bug that verification certified and someone found later is the most valuable
data this team has. It is a known defect at a known commit, so it can be used to
measure any future verifier.

- *Signal:* each escaped bug becomes an eval case (pre-fix commit + expected
  finding) within the retro that records it.
- *Signal:* a change to a verify prompt, verifier model or gate is not adopted
  until it has been run against the eval set.

### Outcome 4: improvement is measured, not felt

- *Signal:* consecutive retros share Scorecard rows, so the trend can be read off
  two tables.
- *Signal:* a claimed improvement cites the window and the sample size behind
  it.

## The loop

### 1. Capture

Record the event at the time it happens, with its identifiers:

- **execution id** (`syn execution show <id>`), and the phase that failed;
- **commit SHA** the run checked out, read from that execution's own record:
  its `git_checkout` event, `checked_out_commits` on
  `WorkspaceProvisionedForPhase`, or the SHA its verify artifact names. A PR's
  current head is not this: a fix round moves the head after verification;
- **what was observed**, as pasted output (log line, exit code, error text),
  not paraphrase;
- **what was expected.**

Use the stored record. `syn execution show`, the event stream, `gh pr view` and
`git log` are evidence; your memory of the run is not. Recording later is fine,
but the identifiers have to be looked up, not recalled.

Where it goes: the PR, an issue, or the retro's working notes, wherever the next
reader will see it. A paper cut that only exists in a scratchpad gets lost when
the session ends.

### 2. Classify

Every failure gets exactly one primary category. The retro scorecards so far use
finer, ad hoc rows ("Codex capacity / quota", "phase deadline (exit 124)", "OOM
at the workspace cap", "orphaned by an API restart"). This five-way split is the
summary those rows fit into, and each one sends the fix somewhere different:

| Category | Means | Seen in the retros as | Fix goes to |
|---|---|---|---|
| **Platform gap** | the platform could not do what a reasonable task needed | phase deadline, OOM at the cap, orphaned by restart, compose drift | a platform issue, with the image or deployment it was measured on |
| **Vendor outage** | a provider was down, at capacity or out of quota | Codex capacity (29) and quota (3) on 2026-10-06 | retry/fallback policy, never a workflow rewrite; excluded from the run failure rate |
| **Agent error** | the agent had what it needed and got it wrong | a defect it wrote or certified | an eval case (step 3), then a prompt, model or gate change |
| **Orchestrator error** | whoever dispatched or merged got it wrong | the ~3 h idle on a blocking question; batch approval of 6 PRs | orchestrator practice, written into a skill or runbook |
| **Spec error** | the task or brief was wrong | a false premise an agent correctly refused | the brief or the workflow's premise phase |

An agent that refuses a false premise or stops at a platform gap has not made
an agent error. The 2026-10-06 retro counts 20 such refusals as a good outcome,
and two of them turned into needed fixes (#1650/#1651, #990/#1652). Score the
refusal as correct, and classify whatever caused it.

### 3. Convert

**An escaped bug becomes an eval case.** An escaped bug is one that a
verification phase certified as clean, and then a later reviewer, a second
verifier or production found. Each case records:

- the PR, and the **head commit before the fix** (the commit verification
  certified, or the fix commit's parent on the PR branch);
- the **expected finding**: the defect in one sentence, specific enough that a
  verdict either names it or does not;
- the **pass condition**: re-verifying that commit ends in a *blocked* verdict
  that names the defect. Being blocked for some other reason does not count as a
  pass.

Run it with `sdlc-reverify-pr-v1`, pinned to that commit through an eval:

```
syn eval create --name "escaped: #1652" --goal "verify blocks: binary reads 404" \
  --repo syntropic137/syntropic137@<pre-fix-sha>
syn workflow run sdlc-reverify-pr-v1 -t "#1652" --eval <eval-id>
syn eval runs <eval-id>
```

The baseline pins the SHA, and every run of the case shows up under
`syn eval runs`.

**This does not work yet. Issue #1658 tracks it.** The `prepare` phase refuses
a merged PR, checks out the PR's live head instead of the pinned SHA, and merges
`origin/main`, which for an escaped bug already contains the fix. Until #1658
lands, a seed case run as written passes for the wrong reason. Record the cases
now so the set exists when the mode does.

Seed cases, from the [2026-10-06 retro](../../../docs/retrospectives/2026-10-06-merge-down-and-the-dropped-start.md):

| Case | Commit to verify | Expected finding |
|---|---|---|
| #1574 (fixed by #1641) | `aab6e95b`, #1574's head as merged (merge df7a99db1) | `ExecutionRequest` keyed by the execution's own id shares the execution's stream in a store keyed by aggregate id alone, so every direct start is dropped as a duplicate |
| #1649 | `7047b1c3`, the parent of fix bd302d76 | an execution id is accepted as an eval id; archive writes into the execution's stream |
| #1652 | `b2f680f0`, the parent of fix 721a8014c | binary artifact reads use the artifact id, but MinIO keys by workflow, execution and artifact, so every binary read returns 404 |
| #1654 | `123b2520`, the parent of fix 4dae285b2 | `codex exec` reports usage once, after the run, so the per-phase cost limit can never stop a Codex phase |

The three parents are merges of `origin/main` into the PR branch, which is the
head verification was handed. All four passed their own verification against
a test double or fixture that did not behave like the real backend or CLI. The eval
asks whether a verifier will catch them now.

**A recurring failure class becomes an issue with a test or fitness function.**
"Recurring" means a second occurrence, or a first one that obviously belongs to
a class. The issue proposes the check that would have failed:

- a static property across the whole codebase belongs in `ci/fitness/`, ratcheted;
- a behaviour of one code path is a test beside the code (see AGENTS.md, "Why the
  typing ratchets are fitness functions").

The 2026-10-06 class (an in-memory double that does not behave like its real
backend) became contract tests run against both the fake and the real backend
(draft #1655) and ESP #344. Writing "be careful with doubles" in a retro would
not have counted.

### 4. Change

Change one thing at a time (a prompt, a model, a gate) and follow
[`workflow-experimentation`](../workflow-experimentation/SKILL.md): a new
workflow id for the treatment, the control left untouched, outcomes registered
in advance. A change that touches two variables cannot be credited to either.

### 5. Measure

Before adopting the change:

1. **Run the eval set** against it. A verifier change that misses a case the old
   verifier caught is a regression, whatever else it gains.
2. **Record the Scorecard numbers** for the window it ran in:

| Measure | Definition | Why this one |
|---|---|---|
| Escaped defects per merged PR | defects found after a PR was certified, divided by PRs merged | the quality bar; rework dominates every other cost |
| Cost per merged PR | sum of execution cost in the window, divided by PRs merged | spend that shipped nothing is included, on purpose |
| Run failure rate, excluding vendor outages | failed executions minus vendor-outage failures, over executions started minus vendor-outage failures | otherwise a Codex quota day looks like a bad workflow |
| Owner minutes per PR | owner time spent reviewing, approving and unblocking, divided by PRs merged | the scarce resource the loop exists to save |

These four have not all been recorded yet. The 2026-10-06 Scorecard has spend,
failures by cause and PRs merged, but no escaped-defect count and no owner
minutes. Record whatever you can measure, and write "not recorded" for the rest
rather than leaving a row out. That is how the 2026-10-06 retro handled the
10-04 retro's missing spend.

Quality comes first. A cost or latency gain counts only if escaped defects per
merged PR held flat (workflow-experimentation, Outcome 3).

### 6. Retro

Follow the [retrospectives README](../../../docs/retrospectives/README.md)
template (What happened, Timeline, Root cause, What we changed, Open
follow-ups), and add:

- **a Scorecard** with a stated window and a column for the previous retro, as
  the 2026-10-06 retro does against 2026-10-04. Reuse that retro's rows and add
  new rows; do not rename them, or the comparison is lost;
- **the eval cases added** in this window, by PR and commit;
- **an index row** in the README.

The README's rule applies here too: a retro has to link a concrete change. If
nothing changed, the lesson goes under "Open follow-ups" in an existing retro.

## Principles

1. **Judge a past run by its stored record, not by current code.** The question
   is what that run saw: its checked-out commit, its pinned phases, its
   artifacts. Today's code is a different system. Pinned launch records
   `checked_out_commits` on `WorkspaceProvisionedForPhase` (#1615) for this
   reason.

2. **"Verified" means the gates ran.** A verdict counts only if the verifier ran
   the tests and gates and pasted their output. A read-only review that ran no
   tests is a review. Call it that, and do not count it toward the eval or the
   Scorecard as verification.

3. **A green double proves the double.** A behaviour certified only against an
   in-memory adapter or a fixture is not certified. A double needs a contract
   test that runs the same assertions against the real backend.

4. **A lesson has to land somewhere enforced.** Choose a test, a fitness
   function, an eval case, a gate, a prompt line or a skill, in roughly that
   order, because the earlier ones fail a build and the later ones only ask.

5. **Escaped bugs are worth the most.** Each one is a labelled defect at a
   pinned commit, and you cannot buy those. Convert every one.

6. **Count vendor outages, then leave them out.** Record them in the Scorecard
   so the cost is visible, and exclude them from the failure rate so they do
   not hide what a workflow change did.

7. **Keep Scorecards comparable.** A new retro with different rows starts a new
   series. Add rows, keep the old ones, and write "not recorded" when a number
   was not measured.

## Anti-patterns

All of these have been observed here.

- **A lesson written only in a scratchpad.** The 2026-10-04 orchestrator kept 58
  paper cuts in a `papercuts.md` outside the repo. The ones that later became
  issues got fixed. The rest are only as durable as that file.
- **"Verified" meaning a read-only review that ran no tests.** The 2026-10-06
  batch approval ("assume the other 6 are good, assuming they've had the review
  passes") trusted verify phases that could not reach a real store. One of those
  PRs broke every start for about 3.5 hours.
- **A test double certifying behaviour the real backend lacks.** Four cases on
  2026-10-06: #1574 (stream keying), #1649 (same), #1652 (artifact keying), #1654
  (Codex usage timing). All four were green on their own verification.
- **Judging a past run by current code instead of its stored record.** A run is
  declared wrong, or right, because of what the code does now. The run's commit
  and pinned phases are the evidence, and an execution does not store its prompt
  (#1030), so write the prompt down when you dispatch.
- **A retro with no linked change.** A list of observations nothing acts on. The
  README forbids it, and the Outcome 2 signal catches it.
- **A failure count with no cause split.** "66 failed" says nothing until the 32
  vendor outages are separated from the rest.

## Recommended tools by outcome (as of 2026-10-06)

### Outcome: every lesson can be traced to a record

- **`syn execution show <id>` and `syn execution list`.** These give the stored
  phase state, cost and failure for a run.
- **The execution's stored checkout, not the PR's current head.** The commit a
  run certified is the one in its own record: the `git_checkout` event in its
  stream, `checked_out_commits` on `WorkspaceProvisionedForPhase` (#1615), or
  the exact SHA in its verify artifact. `gh pr view <n> --json headRefOid`
  gives the head as it is now, which a later fix round moves, so use it only
  when you are verifying the current head. `mergeCommit` is the merge, not
  anything a verifier saw.
- **`git log --grep`** finds the fix commit for an escaped bug, so its parent
  can be the eval's pinned commit. PR numbers and issue numbers differ (#1649
  fixed issue #967), so look both up.
- **The execution's event stream and phase artifacts.** These show what the
  agent did and reported, as opposed to the run's status.

### Outcome: a lesson ends up where the next run meets it

- **`ci/fitness/` with `fitness-exceptions.toml`** for whole-codebase
  properties, ratcheted.
- **A test beside the code** for one path's behaviour, driven against the real
  backend where a double was the problem.
- **This skill, `dogfooding` and `workflow-experimentation`.** Edit their
  anti-pattern lists when a lesson is about how we work.

### Outcome: escaped bugs become a regression suite

- **`syn eval create`, `syn workflow run --eval <id>`, `syn eval runs <id>`.**
  Pinned launch, the eval aggregate, and runs as a filtered execution list
  ([evals plan](../../../docs/plans/20260929_evals-and-execution-tags.md), steps
  4 to 6).
- **`sdlc-reverify-pr-v1`** as the verifier under test, once #1658 adds a mode
  that verifies the pinned commit as found.

### Outcome: improvement is measured

- **The previous retro's Scorecard**, copied as the starting table.
- **`workflow-experimentation`'s judging order** before reading any cost number.

## References

- [`workflow-experimentation`](../workflow-experimentation/SKILL.md) - running and
  judging the change this loop proposes.
- [`dogfooding`](../dogfooding/SKILL.md) - where work runs, and how delivery is
  confirmed.
- [docs/retrospectives/README.md](../../../docs/retrospectives/README.md) - the
  retro template and index.
- [2026-10-04 retro](../../../docs/retrospectives/2026-10-04-dogfood-orchestrator-day.md)
  - the first Scorecard.
- [2026-10-06 retro](../../../docs/retrospectives/2026-10-06-merge-down-and-the-dropped-start.md)
  - the comparable Scorecard and the seed eval cases.
- [Evals plan](../../../docs/plans/20260929_evals-and-execution-tags.md) - #967.
- #1658 - re-verification cannot yet replay a case at a pinned pre-fix commit.
- #534 - insight loop: analysing stored execution data automatically.
- #1655, ESP #344 - contract tests for in-memory adapters.

## Continual improvement

This skill is maintained in the syntropic137 repository:
https://github.com/syntropic137/syntropic137/blob/main/.claude/skills/learning-loop/SKILL.md

The seed-case table and the #1658 caveat are the parts that will go stale. When
an escaped bug is converted, add its row. When #1658 lands, replace the caveat
with the actual invocation and the first run's result. When a Scorecard measure
is first recorded, remove it from the "not recorded" note. Apply the loop to
this skill too: if a lesson had to be re-learned because the skill missed it,
add it to Anti-patterns with the execution id that found it.
