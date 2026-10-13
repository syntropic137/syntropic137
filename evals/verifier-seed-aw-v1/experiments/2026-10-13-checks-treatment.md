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
field, the cases and their pins (suite v2, the same six cases as v1), the
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

Suite `verifier-seed-aw-v1` v2. One run per case per arm.

- **Train defects (3):** `execute-stderr-merged-into-stdout`,
  `replay-error-result-drops-verdict`, `scripted-agent-tests-not-in-ci`.
- **Train controls (2):** `clean-runtime-exposure-docs`,
  `clean-staged-teardown`.
- **Holdout (1):** `replay-keeps-recorded-verdict`. It is not read until the
  decision below is made, and then once.

Control arm: the v1 baseline runs in `launches.jsonl` stand as the control
(the workflow, prompt, cases and pins are unchanged from v1), so the control
is not re-run. Treatment arm: one v2 run per case under
`eval-verify-pinned-codex-checks-v1`.

v1 baseline (keyword judge), over all six cases: catch 2/4, false-block 2/2.
Read from `score --version 1 --split train` before the treatment is judged,
so both arms are compared on train cases only.

## Metrics

- **Primary:** catch rate on the 3 train defects (blocked, and a blocking
  finding the keyword judge matches to the expected defect and file).
- **Guard:** false-block rate on the 2 train controls. It must not rise
  above the control arm's.
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

One treatment run per case, six runs in all, then stop and score. No
re-runs to change a result: a run that ERRORs (no verdict) is re-launched
once, and recorded as an error if it errors again. The holdout case is
scored once, after the train decision is written below.

## Limits stated up front

- Three train defects and two train controls. A change of one case is the
  whole difference; this is a screen, not an estimate. A positive result is
  confirmed on a larger suite before it is generalised.
- The guard rests on two controls, one of them docs-only. Suite v2 found no
  further control meeting the README's rules (see `suite.yaml`'s v2 note).
- The control arm's runs are from 2026-10-13 and the treatment's will be
  later; `gpt-sol` is an alias, so a model update between them would be a
  second variable. Record the resolved model of each treatment run.

## Results

Not run.
