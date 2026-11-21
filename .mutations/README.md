# Mutation evidence: #897 slice H

Patches 01-05 are killed by a test in `apps/syn-api/tests/test_897_metrics_reports_unpriced_work.py`, 06-09 by one in `packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_897_canonical_totals_coverage.py`. Each test passes on the clean head.
In a workspace run, each patch was applied and the whole file run; these are the failures recorded:

| Patch | Bug it re-introduces | Killed by |
|---|---|---|
| 01-metrics-drop-unpriced-sum | `/metrics` reports `unpriced_observation_count=0` whatever the rows hold | `TestGlobalMetrics::test_two_unpriced_executions_sum` (also `test_wholly_unpriced_work_reads_unpriced`, `test_partly_priced_work_reads_as_a_lower_bound`, `test_tokens_and_money_read_one_source`, `TestWorkflowScopedMetrics::test_other_workflows_coverage_and_money_are_excluded`) |
| 02-metrics-plain-dollar-display | `/metrics` renders a plain `$X` and ignores coverage | `TestGlobalMetrics::test_partly_priced_work_reads_as_a_lower_bound`, `TestGlobalMetrics::test_wholly_unpriced_work_reads_unpriced` (also both `TestWorkflowScopedMetrics` tests) |
| 03-metrics-workflow-scope-leaks-global-coverage | `?workflow_id=` reads the global canonical totals, so other workflows' money and coverage leak in | `TestWorkflowScopedMetrics::test_other_workflows_coverage_and_money_are_excluded`, `TestWorkflowScopedMetrics::test_workflow_with_no_executions_reads_nothing` |
| 04-runs-drop-unpriced-count | `/workflows/{id}/runs` drops each run's unpriced count | `test_each_run_reports_its_own_coverage` |
| 05-runs-plain-dollar-display | `/workflows/{id}/runs` renders a plain `$X` and ignores coverage | `test_each_run_reports_its_own_coverage` |
| 06-canonical-totals-drop-unpriced-turns | canonical totals count unpriced summaries but not unpriced turns | `test_unpriced_summaries_and_turns_are_counted_beside_the_money`, `test_two_unpriced_groups_each_add_their_own_count`, `test_a_workflows_turns_are_narrowed_to_its_executions` |
| 07-canonical-totals-count-priced-turns | a session's turns on a RATED model are counted as unpriced | `test_unpriced_summaries_and_turns_are_counted_beside_the_money` |
| 08-canonical-totals-count-zero-token-turns | zero-token turns (a priced zero, #890) are counted as unpriced | `test_zero_token_turns_are_not_counted` |
| 09-canonical-totals-count-priced-groups | priced groups add their observations to the unpriced count | `test_priced_history_is_one_aggregate_and_reads_no_turns`, `test_unpriced_summaries_and_turns_are_counted_beside_the_money` |

No Docker is needed: `just mutation-evidence 2338 "apps/syn-api/tests/test_897_metrics_reports_unpriced_work.py packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_897_canonical_totals_coverage.py" false`.
