# Evals

Evals are how this repo knows a workflow change helped. Each suite lives in
`evals/<suite-id>/` with a `README.md` (how cases are chosen), `suite.yaml`
(what it measures, which workflow and models, version history) and `cases/`.
Read the suite's README before running it, because the rules for a valid case
differ by kind.

## Kinds

| Kind | Asks | Scored by | Example |
|---|---|---|---|
| verifier | does verify block a known bug and certify a clean change? | blocked and names the defect; certified on controls | `verifier-seed-v1`, `verifier-seed-aw-v1` |
| implementer | given the problem, does the agent fix it? | hidden tests from the real fix | `implementer-seed-v1` |
| screening | is a cheaper component good enough? | per-suite | `feedback-screening-v1` |
| end-to-end | does the whole workflow, from commit and issue, produce a mergeable correct PR? | hidden tests at the final head, plus verify outcome, cost and time | none yet: E4 (`docs/experiments/2026-10-20-end-to-end-replay.md`, PR #2019) is preregistered but blocked because the implement prompts merge and read `origin/main`, which carries the fix |

Single-phase kinds are screening. They can rule an arm out cheaply; they cannot
promote one alone.

## Commands

```
uv run python scripts/eval_suite.py check                 # git only: every pin, fix and control re-read
uv run python scripts/eval_suite.py launch --suite <id>   # dispatches runs; see --help for split/version
uv run python scripts/eval_suite.py score  --suite <id>   # catch rate over defects, false-block rate over controls

uv run python scripts/eval_implementer.py check           # git only
uv run python scripts/eval_implementer.py admit [--case]  # runs hidden tests: empty patch must FAIL, real fix must PASS
uv run python scripts/eval_implementer.py score --case <id> --patch <diff>
```

Read `--help` before launching. Launches cost real quota.

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
- **Call a cheaper arm "quality-neutral" only when the paired difference's
  interval excludes the drop you would tolerate** (say -5pp). Inconclusive is
  not neutral.
- **Cost, wall-clock and tokens are columns of every eval run**, beside the
  score, so one run answers both the quality and the cost question.
- **Hidden tests can certify wrong fixes.** Public benchmarks pass 15-30% of
  patches that differ from the reference fix (UTBoost, PatchDiff 2025). Add a
  differential or adversarial test per implementer case where one test is the
  only judge.

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
