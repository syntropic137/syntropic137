# Plan: k trials per eval case, pass@k / pass^k / flakiness, infra errors apart (#2108)

Status: DRAFT, codex rounds 1 and 2 findings applied. Owner of the lane:
syn137_workflow-mgmt (OKR okrs-51p.5).

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

- per case and cohort: judged trials, passes, infra errors, pending, pass@3,
  pass^3, flaky yes/no, trials still needed;
- per eval set and cohort: mean pass@3 and pass^3 (conditional, and bounded
  over infra errors), flakiness, the flaky cases, case coverage against the
  roster, infra share;
- per A/B: both cohorts on the same roster and bases, with a paired
  difference and its interval.

## 3. What already exists (and is reused, not rebuilt)

| Piece | Where | What it gives #2108 |
|---|---|---|
| Eval aggregate, one stable eval per suite case | `domain/aggregate_eval/`, `EvalId.for_key` (#1920) | the case identity; every version and every arm adds runs to the same eval |
| Baseline, frozen at the first admitted run | `EvalFrozen`, `slices/execute_workflow/source_commits.py` | the commit every launched run of the eval checks out |
| Recorded starting checkout per execution | `starting_checkout` on the replayed execution (`test_967_the_checkout_is_verified_before_the_agent.py`) | per-trial proof of the base it actually ran on |
| Association kind | `WorkflowExecutionSummary.association_kind` = `launched` or `attached` | which runs were launched pinned, and which were attached afterwards |
| `EvalRunScored` (verdict PASS/FAIL/ERROR, scorer, scorer_version) | Lane 1, Eval stream | the stored per-trial verdict |
| `summarize()` | `domain/read_models/eval_runs.py` | the one place pass rate and variants are decided |
| `FailureClassification` on every failed execution | `aggregate_execution/value_objects.py`, `WorkflowExecutionSummary.failure_classification` | `platform` vs `correct_refusal` / `task` / `unclassified` |
| Image manifest per phase | `IsolationStartedEvent.image_manifest`, replayed per phase (#1913) | image provenance, when the image ships `/opt/agentic/version.json` (it often does not yet) |
| Launch ledger and stable eval lookup | `scripts/eval_suite.py` | dispatch and scoring of verifier suites |

So #2108 is mostly a read-model and harness change. It adds no aggregate and
no event type.

## 4. Vocabulary (orchestration context)

Added to `docs/architecture/orchestration-ubiquitous-language.md`:

- **Trial**: one launched run of an eval. Attached runs are members, not
  trials.
- **Eval Set**: the evals that carry one suite tag (`suite:<eval_suite>`).
- **Roster**: the cases of one eval-set version, with split and polarity
  (section 5.1). Coverage and pairing are computed against it.
- **Cohort**: the trials of one roster that share a declared treatment and
  scoring protocol (section 5.2).
- **Trial Outcome**: `pass`, `fail`, `infra_error` or `pending`, by the
  ordered rule in section 6. Distinct from **Verdict**, the scorer's word.
- **Infra Error**: a trial whose result says nothing about the agent. Never a
  pass or a fail in the conditional figures; a fail in the lower bound.
- **pass@k**, **pass^k**, **Flaky Case**: section 7.

Reserved, not used: "attempt" (trigger limits), "sweep" (admission opening
sweep), "variant" for this purpose (it already names the observed-model
grouping in `summarize()`, which stays as it is).

## 5. Decision 1: roster and cohort

### 5.1 Roster

Suite tags name evals that exist, not cases never launched, and they carry no
split. So the roster is written onto the evals before anything is launched:

- `eval_suite.py register --suite DIR` (idempotent, part of `launch`) creates
  every case's stable eval and tags it `suite-version:<n>`, `split:<s>`,
  `polarity:<defect|clean>`. Tags accumulate: a case in v7 and v8 carries both
  version tags. Split never changes (`evals.md`), so its tag never changes.
- The roster of version n is the evals tagged `suite:<eval_suite>` and
  `suite-version:<n>`. A rostered eval with no trials is a case with n = 0 and
  counts as short, never as absent.
- `register` refuses an eval whose existing split or polarity tag disagrees
  with the case file.

### 5.2 Cohort key

Fixed at launch from what was declared, so a run that never reached a model
or a scorer still belongs to its cohort:

| Part | Source | Why |
|---|---|---|
| roster (eval set + version) | trial tag `suite-version:<n>` | a case changed between versions is another question |
| workflow id + workflow version | execution summary | an edited workflow is another treatment |
| declared models | trial tag `models:<models_digest>` (first 32 hex of sha256 of the models map, so the tag fits 64 chars) plus `model:<phase>:<id>` per phase, both written by `declared_model_tags` | the model is part of the measurement; declared, not observed, so early failures still join |
| scoring protocol | trial tag `scorer:<scorer protocol id>` | a different judge is a different ruler |

All cohort and trial identity is read from the execution's
`inherited_tags` (its launch tags, never edited), not `tags` (editable), so a
later retag cannot move a trial between cohorts. A trial with a missing or
conflicting cohort tag in `inherited_tags` is excluded as `not_a_trial`.

Declared models must be explicit ids. Existing suites declare aliases
(`opus`, `gpt-sol`, `sonnet` in `evals/verifier-seed-v1/suite.yaml`) and
runtime model identities reject aliases (`apps/syn-api/src/syn_api/model_identity.py`),
so `eval_suite.py check` refuses an alias in any suite launched with
`--trials`, and the suite's version bumps when its aliases are replaced.

Observed models are validation, not key: per phase, the phase's own model
(Lane 2, as `RunReads.own_model` reads it; delegates ignored) must equal the
declared id, or the trial is excluded as `treatment_mismatch` and counted. A
phase that never reported a model (it failed before the agent ran) is not a
mismatch. A scored trial whose `scorer_version` disagrees with its cohort's
protocol is not judged for that cohort until re-scored under it.

## 6. Decision 2: trial outcome, an ordered rule

Inputs: `association_kind`, execution status, `failure_classification`, the
current `EvalRunScored` (absent, or verdict PASS/FAIL/ERROR), and whether the
starting checkout matches the eval's baseline. First matching row wins.

| # | Condition | Outcome |
|---|---|---|
| 1 | `association_kind` is `attached`, or cohort tags missing or conflicting in `inherited_tags` | excluded (`not_a_trial`), counted |
| 2 | a starting checkout IS recorded and differs from the baseline | excluded (`base_mismatch`), counted |
| 3 | an observed phase model contradicts its declared id (section 5.2) | excluded (`treatment_mismatch`), counted |
| 4 | status `not_started` or `running` | `pending` |
| 5 | status `cancelled` or `interrupted` | `infra_error` |
| 6 | status `failed`, classification `correct_refusal` or `task` | `fail`: the agent stopped without the deliverable, whatever the score says |
| 7 | status `failed`, classification `platform` or `unclassified` | `infra_error` (includes failures before provisioning, which record no checkout) |
| 8 | status `completed`, no starting checkout recorded | `infra_error`: a result on an unverified base is not judged |
| 9 | status `completed`, no score recorded | `pending` (unscored) |
| 10 | status `completed`, verdict PASS | `pass` |
| 11 | status `completed`, verdict FAIL | `fail` |
| 12 | status `completed`, verdict ERROR | `infra_error` (#1780: completed with no recorded review verdict is the engine's gap; or the scorer broke) |

An absent checkout (`starting_checkout` is `[]` before provisioning succeeds,
`WorkflowExecutionAggregate.py`) is never a mismatch: rows 4, 5 and 7 keep
those trials as reservations, retry counts and bound inputs. Only a judged
outcome (rows 10, 11, and row 6 once provisioned) needs verified provenance.
Every terminal status crossed with absent/PASS/FAIL/ERROR, with and without a
recorded checkout, is a test (T1).

Why derived, not a new verdict value: the classification and the checkout are
already Lane 1 truth on the execution, and copying them into the score gives
two places to disagree. A re-score or re-classification changes the outcome on
the next read with no migration.

### 6.1 The bias, and how it is bounded rather than thresholded

`FailureClassification` resolves doubt toward `platform` on purpose (budget,
parse failures and unknown causes all land there). For an eval, excluding
those can flatter the agent, and a threshold on infra share does not control
it: a few excluded hard cases can move the score while the share stays low.
So every figure is reported three ways:

- **conditional**: over judged trials only (infra errors excluded);
- **lower bound**: every infra error counted as a fail;
- **upper bound**: every infra error counted as a pass.

The bounds run over the **whole roster** (or split), not only complete cases:
a case short of k or never launched counts as 0 in the lower bound and 1 in
the upper, so dropping incomplete cases cannot select the easy ones. A
promotion or "quality-neutral" call must hold at both bounds. If the bounds
straddle the decision line, the result is `inconclusive` and the remedy is a
top-up, not a judgement. The response also carries infra share per cohort.
The bounds are the honest form of "infra errors are not scored as 0".

Phase deadlines are `platform` today. Splitting agent-caused from
platform-caused deadlines needs evidence the record does not hold (the same
problem `TASK` has, #1392); the bounds cover it meanwhile. Follow-up filed.

## 7. Decision 3: where the metrics are computed

**In the domain read model (`eval_runs.py`: the outcome rule, the estimators
and a new eval-set summary beside `summarize()`), called by the API at query
time. Not a new projection.**

The handoff suggested a projection. The existing design rejects one on purpose
(`slices/list_evals/projection.py` docstring): an eval's runs are joined at
read time from the execution list, the eval's score documents and Lane 2. A
metrics projection would subscribe to all three, copy their facts, and could
then disagree with the execution view. The rule that matters is "no client
math": one domain function computes each number server-side, and the API, CLI
and UI all read it. Cost at the north star: about 40 evals x k trials x a few
cohorts, a few hundred rows per request. If set reads get hot, the same
function can back a cached projection later without changing the API.

Estimators, per case and cohort, with `n` judged trials and `c` passes:

- pass@k = 1 - C(n-c, k) / C(n, k)
- pass^k = C(c, k) / C(n, k)
- flaky = pass@k > 0 and pass^k < 1

At n = k they reduce to "passed at least once" and "passed every time", the
#2108 definitions. For n > k they are the unbiased estimators (Chen et al. 2021
for pass@k; the same counting argument for pass^k). For n < k the case reports
`trials_short` and no metric. The bounds in 6.1 use the same formulas with
infra errors recoded.

Set level, per cohort: mean pass@k and pass^k over roster cases with n >= k,
flakiness = their difference, the flaky cases, and **coverage**: roster size,
cases complete, cases short, cases never launched. The conditional mean over
partial coverage is labelled partial and is descriptive only; decisions read
the roster-wide bounds of 6.1. Split is a filter (`split=holdout`), read from the roster tags.

The #2108 example (10 cases, 7 always, 2 sometimes, 1 never) yields 90% / 70%
/ 20% and is a unit test.

## 8. Decision 4: where k-trial dispatch lives

**In the harness (`eval_suite.py launch --trials k`, default 3), with every
count the server's, and one operator at a time.**

- `launch --trials k` registers the roster (5.1), then starts k executions per
  case into the case's stable eval, tagged with the cohort key and
  `trial:<batch id>/<i>`, and appends one ledger line per trial.
- `trials_short = max(0, k - judged - pending)`: in-flight trials are
  reserved, so a second top-up while trials run launches nothing for them.
- `launch --top-up` launches exactly `trials_short` per case and **refuses to
  start while the cohort has any pending trial**, so repeated or overlapping
  top-ups cannot overlaunch. Concurrency between two operators is out of
  scope: the lane is the only launcher, and the ledger is committed.
- Retry cap: a case whose infra errors in the cohort reach k reports
  `exhausted: true` and `trials_short = 0`. This is advisory (the harness obeys
  it); the server reserves nothing. Server-enforced admission belongs to the
  platform-owned eval run in section 14.
- Bases do not depend on timing (section 9), so trials need not share a
  minute; dispatch stays inside the orchestrator's slot cap.

Why not a ProcessManager now: starting k executions is k commands with no
"what's next" decision beyond a count the server already computes. A
ProcessManager earns its place when the platform owns scoring too.

## 9. Decision 5: how matched bases are guaranteed

1. **By the baseline, checked per trial.** Every launched run of an eval
   checks out the frozen baseline and records its `starting_checkout`. Rule 1
   of section 6 excludes any trial whose recorded checkout differs from the
   eval's baseline, and any attached run, so membership alone never makes a
   trial. Two A/B arms are two cohorts launched into the same evals.
2. **Only pin-safe workflows are eval subjects.** A workflow whose prompts
   fetch or merge `origin/main` (premise in `sdlc-implement-v3/v4/v7`) moves
   off the pin after the checkout. Until #2055, only `workflows/evals/*`
   workflows qualify, and `eval_suite.py check` refuses a suite workflow whose
   phase prompts merge, pull or rebase onto the default branch. This is why
   the v7 A/B could not pair: it was not an eval.
3. **Drift that is not a base.** The image can change between trials (a pit
   stop mid-batch). `IsolationStartedEvent.image_manifest` records it per
   phase when the image ships `/opt/agentic/version.json`, which current images
   often do not (open AW ask). The set response lists the distinct manifests
   per cohort and the count with none. Not part of the key: it would split
   every batch that spans a deploy. Launch a batch between pit stops.

## 10. Audit: the independent-referee rule

Rule from #2108: the harness seeds, the agent runs isolated, output is
collected, a verifier the agent cannot see or influence scores it, and the
agent never grades or provisions itself. Three questions per suite: who
provisions the subject, can the subject reach the judge or the answer, and who
carries the verdict.

| Suite | Subject provisioned by | Can the subject reach the answer? | Verdict carried by | Result |
|---|---|---|---|---|
| verifier-seed-v1, verifier-seed-aw-v1 | platform, pinned checkout verified | **yes**: the full clone of the default branch holds `evals/*/cases/*.yaml` (expected file and keywords) and the later fix; the workspace has a GitHub credential and network. The prompt forbids looking; that is not isolation | host-side `eval_suite.py score` (keyword judge, optional LLM judge) | **isolation unproven**, judge itself independent |
| implementer-seed-v1 | platform, pinned checkout verified | **yes**, same channels (README "Leakage") | `eval-implement-score-v2`: an agent runs the deterministic scorer and reports; the scorer makes its own worktree at the pin from a default-branch checkout | **fails**: leakage, and an agent transports the verdict |
| feedback-screening-v1 | recorded fixtures, no agent run | n/a | n/a | not applicable |
| E4 replay (preregistered) | platform | yes, via `origin/main` (#2055) and leakage (#2056) | host-side hidden tests + reverify | blocked, not run |
| in-run verify of any sdlc workflow | n/a | n/a | the workflow judging its own implement phase | **never a referee**: an in-run verify verdict is part of the treatment, never the eval score. Stated in the vocabulary and in `evals.md` |

Fixes:

1. **Leakage, both suites.** #2056's pinned clone (shallow fetch of the pin, no
   other refs), no repository credential in the subject's phase, and egress
   without github.com close all three channels for verifiers and implementers
   alike: a shallow clone at the pin holds no case file added after it and no
   later fix. Until then every set response for these suites carries
   `isolation: unproven`, and no promotion decision rests on them alone.
2. **One judge across arms.** Per-arm judges would compare treatments under
   different rulers. The LLM judge becomes a fixed two-family panel (one
   Claude, one codex model, pinned ids) applied to every arm of a comparison,
   and its id is the cohort's scoring protocol. Disagreement between the two
   is `unclear`, as today. The keyword judge stays OR-ed in.
3. **A deterministic referee for implementer runs.** The script's exit code is
   the verdict; no agent carries it. `eval_implementer.py score` runs on the
   orchestrator host inside a throwaway container from the pinned workspace
   image, with this contract:
   - the scorer is `scripts/eval_implementer.py` at a recorded commit of this
     repo, and that commit is part of `scorer_version`;
   - the repository arrives as a git bundle holding the pin and the fix
     commit, and **each submodule as its own bundle** holding every commit the
     pin and the fix reference, unbundled into separate clones at the
     submodule paths, because `_check_out_submodules` clones each one from a
     local repository at its path (`scripts/eval_implementer.py:493-522`);
   - **preparation, network on**: the scorer's own preparation runs in full,
     which today is a worktree and `uv sync` at `fix_commit` (to collect the
     intended hidden test ids) and a second worktree and `uv sync` at the pin;
     the plan adds a `prepare` subcommand to `eval_implementer.py` that does
     exactly this and nothing else, so the handoff is one command, not a copy
     of its internals;
   - **offline**: the network is cut (`docker network disconnect`), then
     `score --prepared` applies the patch to the prepared pin worktree,
     restores the hidden tests and runs them, with no fetch or sync allowed
     (a sync attempt is an ERROR, not a retry);
   - the patch comes from the implement run's `implement.patch` artifact,
     downloaded through the API;
   - the result is recorded as `EvalRunScored`, scorer `eval_implementer.py`.
   The reference fix (must PASS) and the empty patch (must FAIL) run through
   this exact path before any agent trial is scored.
4. **Provisioning.** The subject is never self-provisioned in any suite: the
   platform checks out and verifies the pin before the agent starts. The
   current implementer referee is the exception that fix 3 removes (its agent
   sets up the scoring worktree).

## 11. Paired A/B report

`GET /eval-sets/metrics?suite=<eval_suite>&version=<n>&split=<s>` returns one
block per cohort with per-case rows over the same roster. For two cohorts on
one roster it adds a comparison:

- the estimand is the **per-case pass^k from exactly the first k judged
  trials** of each case (by start time), which is binary, so the discordant
  counts (A only / B only) are well defined; cases short in either cohort are
  listed and left out of the pair;
- the response carries the discordant counts, the exact McNemar p, and a
  paired bootstrap 95% interval on the difference in mean pass^k (10,000
  resamples over cases, fixed seed, computed in the domain so every reader
  gets the same interval);
- **worst-case paired bounds**: the difference A - B at the two adverse
  assignments, A_lower - B_upper and A_upper - B_lower (each over the whole
  roster, 6.1), each with its own paired bootstrap interval. Same-direction
  recodings (both lower, both upper) are not reported as bounds: they can both
  show zero while the true difference spans [-1, 1].

A/B decisions follow `evals.md`: holdout split, **paired coverage complete**
(every roster case has k judged trials in both cohorts, or the call is
`inconclusive`), and the interval at both adverse assignments excludes the
tolerated drop. Inconclusive is not neutral.

## 12. Slices and tests

Each slice is one platform run (`sdlc-implement-v3`), dispatched only with the
orchestrator's slot OK. S1 to S3 are the #2108 acceptance; S4 and S5 close the
audit.

| Slice | Change | Tests |
|---|---|---|
| S1 domain | outcome rule, estimators, bounds, cohort key, roster coverage, set summary, paired comparison; `EvalRunFacts` gains `failure_classification`, `association_kind`, `inherited_tags`, `starting_checkout`, baseline | T1 every terminal status x absent/PASS/FAIL/ERROR x checkout recorded/absent, plus attached, base-mismatch and treatment-mismatch rows; T1b a retag of `tags` does not move a trial; T2 the #2108 example gives 90/70/20; T3 an infra error is excluded from n, lowers only the lower bound; T4 n < k reports `trials_short`, no metric; T5 n = 4, k = 3 matches the closed form; T6 two scoring protocols never pool; T7 a rostered case with no trials shows as never launched and marks the mean partial; T8 pending trials reduce `trials_short`; T9 the paired comparison on a fixed fixture gives fixed counts, p, intervals and adverse-assignment bounds; T10 a short case widens the roster-wide bounds |
| S2 API + CLI | per-eval cohort fields; `GET /eval-sets/metrics`; Pydantic responses; `just codegen`; `syn eval` gains a set subcommand (`apps/syn-cli-node/src/commands/eval.ts`) | route tests on the response model; drift check; one route test where an infra trial shows in `infra_error_count` and the lower bound, not in fails |
| S3 harness | `register`, `launch --trials k` with cohort tags, ledger `batch`/`trial`, `launch --top-up` from `trials_short` and refused while pending, `score` prints the server's figures, `check` refuses non-pin-safe workflows | `scripts/tests/test_eval_suite.py`: roster tags written and conflicts refused; k ledger lines per case; top-up launches the server's count; top-up refused while pending; exhausted case launches none; a default-branch merge in a prompt is refused; a model alias in a `--trials` suite is refused |
| S4 implementer referee | `eval_implementer.py prepare` and `score --prepared`; the section 10 fix 3 container path; `eval-implement-score*` retired | reference fix PASS and empty patch FAIL through the container path; a patch that needs the network to pass FAILs; a sync attempt offline is ERROR |
| S5 judge panel | two-family fixed panel as the scoring protocol | unit test that both arms of a comparison get the same protocol id; panel disagreement is `unclear` |

The vocabulary and `.claude/skills/managing-workflows/references/evals.md`
update ride with S1 and S3.

## 13. Dry run before any frozen protocol

Lesson from the A/B: dry-run one unit end to end before freezing. After S1 to
S3 land: `verifier-seed-v1`, `--split train`, 2 cases (one defect, one clean),
k = 3, one cohort, 6 runs (`launch --trials 3 --split train --case <defect> --case <clean>`). Pass: the roster is registered, 6 ledger lines,
every trial's starting checkout equals its eval's baseline, and
`GET /eval-sets/metrics` matches a hand count, bounds included. Then the full
set, then an A/B. Results stay `isolation: unproven` until #2056.

## 14. Out of scope, filed as follow-ups

- A platform-owned eval run (ProcessManager, server-enforced trial admission,
  a deterministic referee phase type), which moves dispatch and scoring off
  the host.
- Splitting phase-deadline failures into agent-caused and platform-caused.
- Shipping `/opt/agentic/version.json` in every workspace image (AW).
- End-to-end replay (#2055) and leakage (#2056): this plan depends on them for
  isolation and for E2E suites, but does not implement them.
- Judge calibration fixtures (#2048).

## 15. Open questions for the owner

1. Default k = 3 for every suite, or k = 5 for holdout promotion decisions?
2. Is the host-side container referee (S4) acceptable on the orchestrator
   host, or must scoring run on the VPS?
3. The two-family judge panel doubles judge cost per scored trial. Accept, or
   keep the single Claude judge with `judge_family_overlap` disclosed?
