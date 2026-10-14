# Preregistration: required checks in the verify prompt (2026-10-13)

Written before any run of the treatment. No v2 run of either arm had been
launched when this file was committed; `launches.jsonl` holds only the six v1
baseline rows. Nothing below may be edited after the first v2 run except the
Results section at the end.

## Question

Does a verify prompt that requires three checks, each with evidence, catch
more of agentic-workspace's escaped defects without blocking more clean
changes?

## Arms (one variable)

| | Control | Treatment |
|---|---|---|
| Workflow | `eval-verify-pinned-codex-v1` | `eval-verify-pinned-codex-checks-v1` |
| Prompt | `workflows/evals/verify-pinned-codex/phases/verify.md` | the same text plus one section, `## Required checks` |

Held constant: the agent (codex, `gpt-sol`, `workspace-write`), every phase
field, the cases and their pins (suite v2), the
judge (`KeywordJudge`), and the scorer (`scripts/eval_suite.py score`).
`scripts/tests/test_eval_suite.py` fails if the two workflows differ in
anything but the prompt section, id, name and description.

The three required checks:

1. for every changed public symbol, its callers in the consuming
   repositories (syntropic137 for an agentic-workspace change) and whether
   their contract holds;
2. for every new or changed test file, the CI job that runs it, else a
   blocking finding;
3. for each critical behaviour claim, the test that would fail if its line
   were reverted, by reading only.

## Hypothesis

Each of the four train-and-holdout defects in this suite escaped a verifier
that did not do one of these checks: AW#47 broke `execute`'s callers
(check 1), AW#49's package tests were never run by CI (check 2), and AW#49's
replay closed with a verdict syntropic137 does not read (check 1). Requiring
the checks should raise the catch rate. It may also make the verifier block
more, since every check can yield a finding.

## Sample

Suite `verifier-seed-aw-v1` v2: seven live cases. One run per case per arm,
both arms launched on v2, so they are compared on exactly the same cases.

- **Train defects (3):** `execute-stderr-merged-into-stdout`,
  `replay-error-result-drops-verdict`, `scripted-agent-tests-not-in-ci`.
- **Train controls (3), all code and tests:** `clean-staged-teardown`,
  `clean-event-type-identifiers` and `clean-deployment-identity` (both new
  in v2).
- **Holdout (1):** `replay-keeps-recorded-verdict`. It is not read until the
  decision below is made, and then once.
- **Not in the sample:** `clean-runtime-exposure-docs`, retired in v2
  (docs-only). Its v1 run stays in `launches.jsonl` and scores under v1; it
  is in no figure below.

Control arm: seven v2 runs under `eval-verify-pinned-codex-v1`. Treatment
arm: seven v2 runs under `eval-verify-pinned-codex-checks-v1`. Fourteen runs
in all. The six v1 baseline runs are not reused: v1's case set differs from
v2's, and re-running the control beside the treatment keeps the `gpt-sol`
alias resolving to the same model in both arms.

v1 baseline (keyword judge), over all six v1 cases: catch 2/4, false-block
2/2. It is context only; no decision below reads it. Both arms are scored
with `score --split train` on their v2 tags.

## Metrics

- **Primary:** catch rate on the 3 train defects (blocked, and a blocking
  finding the keyword judge matches to the expected defect and file).
- **Guard:** false-block rate on the 3 train controls. It must not rise
  above the control arm's.
- **Reported beside the guard:** for each treatment block of a control,
  whether every blocking finding rests only on check 2 finding no CI job.
  The three controls are pinned in imported history, which has no
  `.github/` (README "What differs"), so check 2 can fire on them for a
  reason that is not in the change. Such a block still counts as a false
  block in the guard; it is named so the reader can see it, and it is the
  first thing to fix in the treatment if the guard fails on it.
- **Mechanism check (not scored):** the treatment's report has a
  `## CHECKS` section with evidence for each of the three checks. A run
  without it is a run where the treatment did not happen; it is reported
  as such and not counted as a treatment result.

## Decision rule

- **Adopt** (the checks go into the platform verify prompt, as a separate
  change): the treatment catches more train defects than the control, and its
  train false-block count is no higher.
- **Reject:** it catches no more, or its train false-block count is higher.
- **No difference** is a legitimate outcome and is reported as one.
- A clean control the treatment blocks is read against verifier-seed-v1's
  README: if both strong verifiers block it, it is a candidate defect, and
  the finding is investigated before the guard is called failed.

## Stopping rule

Fourteen runs (seven per arm), then stop and score. No re-runs to change a
result: a run that ERRORs (no verdict) is re-launched once, and recorded as
an error if it errors again. The holdout case is scored once per arm, after
the train decision is written below.

## Limits stated up front

- Three train defects and three train controls. A change of one case is the
  whole difference; this is a screen, not an estimate. A positive result is
  confirmed on a larger suite before it is generalised.
- The brief asked for 3-4 strong code controls. v2 has three in train
  (`suite.yaml`'s v2 note lists what was re-read and why each other merge is
  excluded); a fourth would need a merge that has not yet had 30 quiet days.
- Every control predates CI in this repository's history; every defect pin
  has `.github/workflows/ci.yml`. Check 2 therefore sees a different world
  on the two polarities, which favours the treatment's catch rate on
  `scripted-agent-tests-not-in-ci` and works against its guard.
- Check 1 asks for callers in syntropic137, but the launcher hands the
  workspace only the suite's repository. Each treatment report's `## CHECKS`
  section says whether that evidence was available; a check 1 finding
  without it is reported as unverifiable, not counted for or against.
- `gpt-sol` is an alias. Launch the two arms together and record the
  resolved model of every run; a run whose model differs from its pair's is
  reported, not scored.

## Results

Fourteen runs, suite v2, keyword judge, one run per case per arm.

| | Control (`eval-verify-pinned-codex-v1`) | Treatment (`eval-verify-pinned-codex-checks-v1`) |
|---|---|---|
| Train defects caught | 1/3 | 2/3 (adds `scripted-agent-tests-not-in-ci`) |
| Train controls blocked | 3/3 | 3/3 |
| Holdout `replay-keeps-recorded-verdict` | caught | not caught |

**Decision: not adopted yet.** On the primary metric the treatment catches
one more train defect. The guard cannot be read. A guard only means
something if the controls are clean, and these were not. Both arms blocked
every control, and the blocks were true or could not be investigated:

- `clean-staged-teardown` (exec-ca359d2d2e15 control, exec-479751d1afef
  treatment): the `lock.locked()` waiter race at `providers/docker.py:715`
  and `_remove` ignoring `docker rm`'s exit status at `:814`. AW#56 fixed
  both (`e241fdf`). Both arms also named the shield/cancel at `:755`, which
  #56 lists as not verified. A real defect, so these are correct blocks,
  not false ones.
- `clean-deployment-identity` (exec-5b26b73f76d9): the probe at
  `tests/integration/test_entrypoint_capabilities.py:4003` cannot tell an
  absent variable from an empty one, and the task asked whether the tests
  prove that. A true finding. It is unfixed on AW main.
- `clean-event-type-identifiers`: no run id or finding was recorded where
  suite v3 could read it, so it was not investigated.

The guard is therefore unmeasured. It has neither passed nor failed. The
"reported beside the guard" breakdown (blocks resting only on check 2) is
not given: the findings for two of the six blocks were not available. The
holdout went the other way (control caught, treatment not). With one run
per arm, that is a single case, reported and not weighed.

**Not done:** the fourteen runs are not in `launches.jsonl`, which holds
only the v1 rows. So `score` cannot reproduce these figures from this
repository. They are the orchestrator's keyword-judge results, as reported
to suite v3. The one model alias `gpt-sol` was not checked per run here.

**Next:** suite v3 (`suite.yaml` v3 note) reclassifies `clean-staged-teardown`
as the defect `teardown-lock-waiter-race`, retires the other two controls,
and adds README rule 4. No current merge passes rule 4, so v3 has no
controls. The treatment is re-tested once a suite has rule-4 controls to
guard it.
