# Evals

Evals are how this repo knows a workflow change helped. Each suite lives in
`evals/<suite-id>/` with a `suite.yaml` and `cases/`. The verifier and
implementer suites also have a `README.md` (how cases are chosen), and their
`suite.yaml` records the eval workflow, each phase's model and the version
history. `feedback-screening-v1` has no README: its `suite.yaml` records the
goal, splits and sources, with recorded fixtures under `recorded/`. Read
whichever the suite has before running it, because the rules for a valid case
differ by kind.

## Kinds

| Kind | Asks | Scored by | Example |
|---|---|---|---|
| verifier | does verify block a known bug and certify a clean change? | blocked and names the defect; certified on controls | `verifier-seed-v1`, `verifier-seed-aw-v1` |
| implementer | given the problem, does the agent fix it? | hidden tests from the real fix | `implementer-seed-v1` |
| screening | is a cheaper component good enough? | per-suite | `feedback-screening-v1` |
| end-to-end | does the whole workflow, from commit and issue, produce a mergeable correct PR? | hidden tests at the final head, plus verify outcome, cost and time | none yet: E4 is preregistered but blocked. Its doc, `docs/experiments/2026-10-20-end-to-end-replay.md`, is not on `main` yet: it is on draft PR #2019 (branch `research/eval-model-selection`), which this lane has adopted. It is blocked because the implement prompts merge and read `origin/main`, which carries the fix |

Single-phase kinds are screening. They can rule an arm out cheaply; they cannot
promote one alone.

## Commands

```
uv run python scripts/eval_suite.py check  [--suite evals/<suite-id>]  # git only: every pin, fix and control re-read
uv run python scripts/eval_suite.py launch --suite evals/<suite-id>    # dispatches runs; see --help for split/version
uv run python scripts/eval_suite.py score  --suite evals/<suite-id>    # catch rate over defects, false-block rate over controls
uv run python scripts/eval_suite.py register --suite evals/<suite-id>  # roster tags on each case eval; idempotent; a conflict writes nothing
uv run python scripts/eval_suite.py launch --suite evals/<suite-id> --trials 3  # k runs per case, one cohort
uv run python scripts/eval_suite.py launch --suite evals/<suite-id> --trials 3 --top-up  # only trials_short; refused while any trial is pending
uv run python scripts/eval_suite.py score  --suite evals/<suite-id> --trials 3  # pass@k / pass^k with bounds from GET /eval-sets/metrics
# verifier-seed-aw-v1 pins agentic-workspace commits: add --repo lib/agentic-workspace to check and launch, or every pin reports missing

uv run python scripts/eval_implementer.py check  [--suite evals/<suite-id>]  # git only
uv run python scripts/eval_implementer.py admit [--case <id>]  # runs hidden tests: empty patch must FAIL, real fix must PASS
uv run python scripts/eval_implementer.py score --case <id> --patch <diff>
```

`--suite` takes the suite's directory. Without it, `eval_suite.py` uses
`evals/verifier-seed-v1` and `eval_implementer.py` uses
`evals/implementer-seed-v1`, so a bare `check` checks only that one suite.
`admit` without `--case` admits every case. Read `--help` before launching.
Launches cost real quota.

## Rules that keep scores comparable

- **The model is part of the measurement.** `suite.yaml` records the eval
  workflow id and each phase's model. Change either and bump the suite version.
- **Report catch rate and false-block rate together.** A verifier that blocks
  everything has a perfect catch rate.
- **Use the holdout split for promotion decisions.** Tune on train, decide
  on holdout, or the suite measures how well you fitted it.
- **Repeat noisy cases and compare paired.** With 20 binary cases the 95%
  interval is about +/-22pp, so one run per case cannot tell a 60% verifier
  from an 80% one. Run 3-5 repeats, compare baseline and arm per case (McNemar
  or bootstrap) and cluster the error by case (Miller 2024, arXiv 2411.00640).
  State n and the interval with every rate.
- **Consistency matters more than one success.** An unattended pipeline needs
  pass^k (all k trials pass), not pass@k. At 75% per trial, pass^3 is about 42%.
- **An infra error is not a fail, and not dropped either (#2108).** The domain
  derives each trial's outcome (`read_models/eval_trials.py`): cancelled,
  interrupted, a `platform`/`unclassified` failure, an unverified base or an
  ERROR score is `infra_error`; a `task`/`correct_refusal` failure is `fail`.
  Every figure comes three ways: conditional (infra out of n), lower bound
  (infra = fail) and upper bound (infra = pass), over the whole roster, where a
  short or never-launched case is 0 and 1. Decide only when both bounds agree;
  straddling means top up, not judge. An in-run verify verdict is part of the
  treatment, never the eval score.
- **A trial is scored under its cohort's scorer protocol.** `launch --trials`
  tags each run `scorer:<protocol>` (the suite version, plus the LLM judge's
  identity when `--llm-judge`); the server counts a score only when its
  scorer_version matches, so `score` refuses another protocol. Switching judge
  means a new cohort, not a re-score.
- **Eval subjects stay on their pin (#2055).** `check` refuses a workflow
  whose prompts `git pull` or merge/rebase the default branch, and with
  `--trials` refuses model aliases (cohort `model:` tags must be explicit ids).
  `launch --trials` registers the whole roster first, whatever `--split`.
- **Call a cheaper arm "quality-neutral" only when the paired difference's
  interval excludes the drop you would tolerate** (say -5pp). Inconclusive is
  not neutral.
- **Report cost and wall-clock beside the score** (`eval_suite.py score` prints
  both; it does not print tokens, and `eval_implementer.py score` prints outcome
  only), so one run answers the quality and the cost question. Add tokens to
  any new score output.
- **Hidden tests can certify wrong fixes.** On SWE-bench, UTBoost
  (arXiv 2506.09289) found patches that passed the original tests but were
  wrong once the tests were strengthened. PatchDiff (arXiv 2503.15223) found
  many test-passing patches behave differently from the reference fix; a
  behavioural difference alone does not make a patch wrong. Add a differential
  or adversarial test per implementer case where one test is the only judge.

## Sources (checked 2026-10-21)

- Anthropic, "Demystifying evals for AI agents" (2026-01-09): start from 20-50
  real failures, multiple trials, grade outcomes, read transcripts, graduate
  saturated capability cases to regression cases.
- Miller, "Adding error bars to evals" (arXiv 2411.00640).
- Panickssery et al., NeurIPS 2024: LLM judges prefer their own outputs, which
  is the evidence behind cross-family verification.
- SWE-rebench and SWE-bench-Live (2025): static suites inflate; keep mining
  fresh cases. Public benchmarks screen models, they do not gate this repo.

## Where cases come from

- **Escaped bugs.** Every bug that reached main after a certified PR becomes a
  defect case pinned at the fix's first parent (`learning-loop`).
- **Clean controls.** Mainline merges no later fix refers to. If two strong
  verifiers both block a control, investigate it as a possible real bug before
  calling it a false block (#1756 was).
- **Implementer cases** need hidden tests that discriminate (`admit`) and a
  task that states the interface the tests use without stating the fix.

## Traps

- **Leakage.** A workspace gets a full clone, GitHub credentials and network,
  so an agent can find the real fix in later history or the fix PR. Treat an
  implementer or replay PASS as suspect until the run had a pinned shallow
  clone and no route to the fix (`evals/implementer-seed-v1/README.md`).
- **A keyword judge is not a judge.** Verifier scores match keywords in the
  report. Check the LLM judge's model is current and calibrated before
  trusting its score.
- **Scores off main.** Results that live only on an open branch, or launches
  missing from `launches.jsonl`, cannot be reproduced. Land the record with
  the finding.

- A dirty tree or shared config leaking between cases measures the harness.
- Inputs passed as prompt text instead of declared inputs change the task.
- A codex auth outage looks like a verifier that refuses everything. Check
  failure class before scoring.
- A run judged by today's code instead of its stored record.
