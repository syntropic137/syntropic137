# Plan: k trials per eval case, pass@k / pass^k / flakiness, infra errors apart (#2108)

Status: DRAFT for review. Owner of the lane: syn137_workflow-mgmt (OKR
okrs-51p.5).

## 1. The problem, measured

- Every eval reports one run per case. With 20 binary cases the 95% interval
  on a rate is about +/-22pp (`.claude/skills/managing-workflows/references/evals.md`),
  so one lucky or unlucky run decides a comparison.
- The v7 vs v4-precheck A/B spent $52.17 on 8 runs and produced 0 scoreable
  pairs (`workflows/sdlc/implement-v7/EXPERIMENT.md`): the arms ran on live
  `main`, about 30 commits apart, so no pair shared a base.
- Today a run that did not complete is scored `ERROR` whatever ended it
  (`scripts/eval_suite.py:run_verdict`). A verifier that gives up and a
  sandbox that broke land in the same bucket, and both leave the rate.

## 2. Outcome

One eval-set run with k=3 yields, from the API and with no client math:

- per case and variant: judged trials, passes, infra errors, pass@3, pass^3,
  flaky yes/no, trials still needed;
- per eval set and variant: mean pass@3, mean pass^3, flakiness (their
  difference), the flaky cases, the infra-error count and share;
- per A/B: both variants' rows for the same cases on the same bases.

## 3. What already exists (and is reused, not rebuilt)

| Piece | Where | What it gives #2108 |
|---|---|---|
| Eval aggregate, one stable eval per suite case | `domain/aggregate_eval/`, `EvalId.for_key` (#1920) | the case identity; every version and every arm adds runs to the same eval |
| Baseline, frozen at the first admitted run | `EvalFrozen`, `slices/execute_workflow/source_commits.py`, `test_967_the_checkout_is_verified_before_the_agent.py` | **matched bases by construction**: every run of an eval checks out the same SHA, verified before the agent starts |
| `EvalRunScored` (verdict PASS/FAIL/ERROR, scorer, scorer_version) | Lane 1, Eval stream | the stored per-trial verdict |
| `summarize()` | `domain/read_models/eval_runs.py` | the one place pass rate and variants are decided; variant key is (workflow id, workflow version, observed models) |
| `FailureClassification` on every failed execution | `aggregate_execution/value_objects.py`, `WorkflowExecutionSummary.failure_classification` | `platform` vs `correct_refusal` / `task` / `unclassified` |
| Launch ledger and stable eval lookup | `scripts/eval_suite.py` | dispatch and scoring of verifier suites |

So #2108 is mostly a read-model and harness change. It adds no aggregate and
no event type.

## 4. Vocabulary (orchestration context)

Added to `docs/architecture/orchestration-ubiquitous-language.md`:

- **Trial**: one run of an eval, i.e. one execution that is a member of it.
  "Trial" is the eval's word for a run; it is not a new entity.
- **Eval Set**: the evals that carry one suite tag (`suite:<eval_suite>`),
  read at one suite version. The suite version is a tag on each trial
  (`suite-version:<n>`), because the evals are shared across versions.
- **Trial Outcome**: `pass`, `fail`, `infra_error` or `pending`, derived by the
  rule in section 6. Distinct from **Verdict**, which is the scorer's word.
- **Infra Error**: a trial whose result says nothing about the agent. Never a
  fail, never a pass; counted on its own.
- **pass@k**, **pass^k**, **Flaky Case**: section 7.
- **Measurement Key**: what two trials must share to be pooled (section 5).

Reserved, not used: "attempt" (taken by trigger limits), "sweep" (taken by the
admission opening sweep).

## 5. Decision 1: the measurement key

Trials pool only when they share all of:

| Part | Source | Why |
|---|---|---|
| eval id | membership | the case, and with it the frozen baseline SHA |
| eval-set version | trial tag `suite-version:<n>` | a case changed between versions is another question |
| workflow id + workflow version | execution summary (already in the variant key) | an edited workflow is another treatment |
| observed models | Lane 2 per phase (already in the variant key) | the model is part of the measurement |
| scorer + scorer_version | `EvalRunScored` | **new**: a keyword-only score and an LLM-judged score are different judges; pooling them mixes rulers |

`summarize()` already keys variants by the first three rows. This adds the
suite version and the scorer to the key. Runs with no `suite-version` tag (an
ad-hoc attach) form their own unversioned group and never enter an eval-set
figure.

## 6. Decision 2: trial outcome and infra_error

The outcome is derived in the domain read model from three facts the store
already holds: execution status, `failure_classification`, and the current
`EvalRunScored` verdict. The scorer keeps recording the verdict it sees; the
domain decides what that verdict means for the agent.

| Execution | Classification | Score | Outcome |
|---|---|---|---|
| running / not started | any | any | `pending` |
| completed | n/a | PASS | `pass` |
| completed | n/a | FAIL | `fail` |
| completed | n/a | ERROR or none, scorer ran | `infra_error` (#1780: completed with no recorded verdict is the engine's gap) |
| failed | `platform` or `unclassified` | any | `infra_error` |
| failed | `correct_refusal` or `task` | any | `fail`: the agent stopped without the deliverable |
| cancelled / interrupted | any | any | `infra_error` |
| any | any | none yet, not pending | `pending` (unscored) |

Why derived, not a new verdict value: the classification is already Lane 1
truth on the execution, and copying it into the score would give two places
to disagree. Re-scoring or re-classifying changes the outcome on the next read
with no migration.

**The bias this rule carries, stated.** `FailureClassification` deliberately
resolves doubt toward `platform` (its docstring: "everything else is
PLATFORM"). For failure accounting that keeps the tally an upper bound; for an
eval it means an agent-caused timeout is excluded instead of failed, which
flatters the agent. Two guards:

1. **Infra share is always shown beside the score.** Every set row carries
   `infra_error_count` and `infra_error_share`.
2. **A set result is `unreliable` when infra share exceeds 20%** of launched
   trials for that variant. The API returns the figures and a
   `reliability: ok | unreliable` field; the threshold is a named constant in
   the domain, not client logic.

Phase deadline: a deadline hit is `platform` today. Splitting agent-caused
from platform-caused deadlines needs evidence the record does not hold (the
same problem `TASK` has, #1392), so it stays `infra_error` and the share guard
covers it. Filed as a follow-up, not solved here.

## 7. Decision 3: where the metrics are computed

**In `summarize()` and a new eval-set summary beside it, in the domain read
model, run by the API at query time. Not a new projection.**

The handoff suggested a projection. The existing design rejects one on purpose
(`slices/list_evals/projection.py` docstring): an eval's runs are joined at
read time from the execution list (status, classification), the eval's score
documents and Lane 2 (models, cost). A metrics projection would subscribe to
all three, copy their facts, and could then disagree with the execution view.
The rule that matters is "no client math": the number is computed once,
server-side, by one domain function, and every surface reads it. Cost at the
north star: an eval set is about 40 evals x k trials x a few variants, a few
hundred rows per request, which is negligible. If set reads get hot, the same
function can back a cached projection later without changing the API.

Estimators, per case and measurement key, with `n` judged trials (pass + fail,
infra errors and pending excluded) and `c` passes:

- pass@k = 1 - C(n-c, k) / C(n, k)
- pass^k = C(c, k) / C(n, k)
- flaky = pass@k > 0 and pass^k < 1 (at n = k: some but not all passed)

At n = k these reduce to "passed at least once" and "passed every time", the
definitions in #2108. For n > k they are the unbiased estimators (Chen et al.
2021 for pass@k; the same counting argument for pass^k), so a top-up that
produces 4 judged trials does not have to discard one. For n < k the case
reports `trials_short = k - n` and no pass@k: a partial case never enters a
set mean.

Set level, per measurement key minus eval id: mean pass@k and mean pass^k over
cases with n >= k, flakiness = their difference, the flaky case list, case
count, cases short, infra totals and reliability. The #2108 example (10 cases,
7 always, 2 sometimes, 1 never) yields 90% / 70% / 20% and is a unit test.

## 8. Decision 4: where k-trial dispatch lives

**In the harness (`scripts/eval_suite.py launch --trials k`, default 3), with
every "how many more" decision made by the server.**

- `launch --trials k` starts k executions per case into the case's stable
  eval, each tagged `suite-version:<n>` and `trial-batch:<id>`, and appends
  one ledger line per trial (the ledger gains `batch` and `trial`).
- `launch --top-up` reads the eval-set summary and launches exactly
  `trials_short` more per case. The harness does no counting of its own.
- **Retry cap, server-side:** a case whose infra errors reach k for a key
  reports `trials_short = 0` and `exhausted: true`. A broken case cannot burn
  quota in a loop; it shows up as exhausted for a human to read.
- Dispatch is serial or batched within the orchestrator's slot cap. Timing no
  longer matters for bases (section 9), so trials do not need the same minute.

Why not a platform `EvalRun` ProcessManager now: starting k executions is k
commands with no "what's next" decision beyond the count, and the count is
already the server's. A ProcessManager earns its place when the platform owns
scoring too (a deterministic referee phase, section 10). That is the follow-up
issue this plan files, not a dependency.

## 9. Decision 5: how matched bases are guaranteed

1. **By the baseline, not by the clock.** Every trial of every arm runs inside
   the case's stable eval, whose baseline is frozen at the first admitted run
   and verified in the workspace before the agent starts. Two arms of an A/B
   are two workflows launched into the same evals. `score` already rejects a
   launch whose eval pins another commit (`_launch_problem`).
2. **Only pin-safe workflows are eval subjects.** A workflow whose prompts
   fetch or merge `origin/main` (premise in `sdlc-implement-v3/v4/v7`) defeats
   the pin. Until #2055 lands, only `workflows/evals/*` workflows qualify, and
   `eval_suite.py check` refuses a suite workflow whose phase prompts contain
   `origin/main` or `git merge`/`git pull` against the default branch. This is
   why the v7 A/B could not pair: it was not an eval.
3. **Drift that is not a base.** The workspace image digest and the platform
   version can change between trials (a pit stop mid-batch). Neither is on
   the execution record today (checked: no image or platform version field in
   the execution summary, detail or events). Follow-up: record both on the
   run's start event, then list the distinct values per key in the set
   response. They should not join the key (it would split every batch that
   spans a deploy); a reader decides. Until then, launch a batch between pit
   stops and note any deploy in the experiment doc.

## 10. Audit: the independent-referee rule

Rule from #2108: the harness seeds, the agent runs isolated, output is
collected, a verifier the agent cannot see or influence scores it, and the
agent never grades or provisions itself.

| Suite | Seeds / provisions | Agent sees the judge? | Who scores | Verdict |
|---|---|---|---|---|
| verifier-seed-v1, verifier-seed-aw-v1 | platform, from the frozen baseline | no: `expected` lives in `evals/*/cases`, not in the brief | host-side `eval_suite.py score`: keyword judge, optional LLM judge | **meets the rule**, one gap below |
| implementer-seed-v1 | platform, from the frozen baseline | **can**: full clone + GitHub credential + network reach the fix (README "Leakage", #2056) | `eval_implementer.py score`, by hand in a workspace or via `eval-implement-score-v2`, where an Opus agent runs the script and reports | **fails twice** |
| feedback-screening-v1 | recorded fixtures, no agent run | n/a | n/a | not applicable |
| E4 replay (preregistered) | would be platform | via `origin/main` (#2055) and leakage (#2056) | host-side hidden tests + reverify | blocked, not run |
| in-run verify of any sdlc workflow | n/a | n/a | the workflow judging its own implement phase | **never a referee**: an in-run verify verdict is part of the treatment, not the score. Stated in the vocabulary and in `evals.md` |

Gaps and fixes:

1. **Verifier suites, judge family.** The LLM judge is `claude-sonnet-5-5`
   (`JUDGE_MODEL`). Against a Claude verifier arm (`verify-pinned`,
   `verify-pinned-sonnet`) that is a same-family judge (Panickssery et al.,
   NeurIPS 2024). Its task is narrow (does a finding name this defect, given
   the root cause) and the keyword judge is OR-ed in, so the risk is small but
   not zero. Fix: the judge family must differ from every scored arm's
   verifier family, or scores carry `judge_family_overlap: true`. Cheapest:
   pick the judge per arm (codex judge for Claude arms). Recorded in
   `scorer_version`, so it splits the key as it should.
2. **Implementer, leakage.** The agent can reach the fix, so it can influence
   its own score with outside information. No implementer PASS counts toward
   pass@k until #2056's pinned clone and no-credential phase exist. Until
   then the set response marks the implementer suite `leakage_open`.
3. **Implementer, an LLM in the referee seat.** `eval-implement-score-v2`
   asks an agent to run a deterministic script and report the result. The
   agent's word is the score. Fix: the referee is the script's own machine
   output, run host-side by `eval_implementer.py score` in a throwaway
   container of the workspace image with networking off, and recorded on the
   eval as `EvalRunScored` (scorer `eval_implementer.py`). No model in the
   loop. Patch handoff: the harness downloads `implement.patch` from the
   implement run's artifacts through the API.
4. **No agent provisions itself anywhere today.** Every suite's checkout is
   the platform's, verified before the agent. Kept as an invariant test
   (section 12, T6).

## 11. Paired A/B report

`GET /eval-sets/metrics?tag=suite:<eval_suite>&version=<n>` returns one block
per measurement key with per-case rows. Two arms in the same set therefore
share case ids and bases, and the response carries, for every pair of keys
that differ only in workflow or model, the discordant counts on pass^k per
case (case passes in A only / B only). The harness prints McNemar's exact p
from those counts; the counts are the server's, the test statistic is
presentation. A/B decisions follow `evals.md`: holdout split, interval
excludes the tolerated drop, inconclusive is not neutral.

## 12. Slices and tests

Each slice is one platform run (`sdlc-implement-v3`), dispatched only with the
orchestrator's slot OK. Slices 1 to 3 are the #2108 acceptance; 4 and 5 close
the audit.

| Slice | Change | Tests |
|---|---|---|
| S1 domain | `TrialOutcome`, outcome rule (section 6), estimators, measurement key with suite version and scorer, set summary, reliability guard; `EvalRunFacts` gains `failure_classification` and `tags` | T1 every row of the section 6 table; T2 the #2108 example gives 90/70/20; T3 an infra_error trial is excluded from n and never lowers pass^k; T4 n < k reports `trials_short`, no metric; T5 n = 4, k = 3 matches the closed form; T6 two scorers never pool |
| S2 API + CLI | per-eval variant fields; `GET /eval-sets/metrics`; Pydantic responses; `just codegen`; `syn eval` gains a set subcommand (`apps/syn-cli-node/src/commands/eval.ts`) | route tests on the response model; drift check; one test that an infra trial shows in `infra_error_count`, not in fails |
| S3 harness | `launch --trials k`, ledger `batch`/`trial`, `launch --top-up` from `trials_short`, `score` prints the server's figures, `check` refuses non-pin-safe workflows | `scripts/tests/test_eval_suite.py`: k ledger lines per case; top-up launches exactly the server's count; exhausted case launches none; `origin/main` prompt refused |
| S4 implementer referee | host-side container scoring, artifact download, `EvalRunScored` recording, `eval-implement-score*` retired | positive and negative control through the new path: reference fix PASS, empty patch FAIL |
| S5 judge family | per-arm judge selection, `judge_family_overlap` | unit test on the selection table |

Vocabulary and `.claude/skills/managing-workflows/references/evals.md` update
ride with S1 and S3.

## 13. Dry run before any frozen protocol

Lesson from the A/B: dry-run one unit end to end before freezing. After S1
to S3 land: `verifier-seed-v1`, `--split train`, 2 cases (one defect, one
clean), k = 3, one arm. 6 runs. Pass criteria: 6 ledger lines, every trial in
its case eval at the case pin, `GET /eval-sets/metrics` returns both cases with
n = 3 or a reported infra error, and the numbers match a hand count. Only then
the full set, then an A/B.

## 14. Out of scope, filed as follow-ups

- A platform-owned eval run (ProcessManager plus a deterministic referee
  phase type), which would move dispatch and scoring off the host.
- Splitting phase-deadline failures into agent-caused and platform-caused.
- End-to-end replay (#2055) and leakage (#2056), which this plan depends on
  for the E2E and implementer suites but does not implement.
- Judge calibration fixtures (#2048).

## 15. Open questions for the owner

1. Infra-share threshold for `unreliable`: 20% proposed.
2. Default k = 3 for every suite, or k = 5 for holdout promotion decisions?
3. Is the host-side container scorer (S4) acceptable on the orchestrator
   host, or must scoring run on the VPS?
