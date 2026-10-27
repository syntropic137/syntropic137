# Mutation evidence for #2108 S1

Each patch re-introduces one bug in the new read-model logic; the named tests
must kill it. Tests: `packages/syn-domain/tests/contexts/orchestration/test_2108_trial_outcome.py`,
`test_2108_trial_metrics.py`, `test_2108_eval_set.py`, `test_2108_eval_set_comparison.py`.

| Patch | Bug | Killed by |
|---|---|---|
| 01-task-failure-is-infra | row 6 dropped: an agent-stopped failure becomes infra | T1 matrix |
| 02-cancelled-is-pending | cancelled reserved as pending | T1 matrix |
| 03-ignore-base-mismatch | off-baseline checkout judged | T1 base mismatch |
| 04-scorer-not-in-cohort | scoring protocol left out of the cohort key | T6 |
| 05-score-protocol-ignored | a score under another protocol judged | T1 protocol |
| 06-pass-at-k-is-rate | pass@k computed as c/n | T5, T2 |
| 07-pending-not-reserved | trials_short ignores in-flight trials | T8 |
| 08-infra-counted-as-fail | infra errors in n of the conditional figure | T3 |
| 09-roster-bounds-over-complete-only | bounds drop short cases | T10 |
| 10-never-launched-not-partial | never-launched case does not mark the mean partial | T7 |
| 11-mcnemar-one-sided | McNemar p not doubled | T9, mcnemar |
| 12-last-k-judged | paired estimand from the last k trials | first-k test |
| 13-same-direction-bounds | A_lower - B_lower reported as the adverse bound | T9 |
