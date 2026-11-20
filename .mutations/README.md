# Mutation evidence: #897 slice H

Every patch is killed by a test in `apps/syn-api/tests/test_897_metrics_reports_unpriced_work.py`. Each test passes on the clean head.
In a workspace run, each patch was applied and the whole file run; these are the failures recorded:

| Patch | Bug it re-introduces | Killed by |
|---|---|---|
| 01-metrics-drop-unpriced-sum | `/metrics` reports `unpriced_observation_count=0` whatever the rows hold | `TestGlobalMetrics::test_two_unpriced_executions_sum` (also `test_wholly_unpriced_work_reads_unpriced`, `test_partly_priced_work_reads_as_a_lower_bound`, `TestWorkflowScopedMetrics::test_other_workflows_coverage_and_money_are_excluded`) |
| 02-metrics-plain-dollar-display | `/metrics` renders a plain `$X` and ignores coverage | `TestGlobalMetrics::test_partly_priced_work_reads_as_a_lower_bound`, `TestGlobalMetrics::test_wholly_unpriced_work_reads_unpriced` |
| 03-metrics-workflow-scope-leaks-global-coverage | `?workflow_id=` reads the global window, so other workflows' money and coverage leak in | `TestWorkflowScopedMetrics::test_other_workflows_coverage_and_money_are_excluded` |
| 04-runs-drop-unpriced-count | `/workflows/{id}/runs` drops each run's unpriced count | `test_each_run_reports_its_own_coverage` |
| 05-runs-plain-dollar-display | `/workflows/{id}/runs` renders a plain `$X` and ignores coverage | `test_each_run_reports_its_own_coverage` |

No Docker is needed: `just mutation-evidence 2338 "<ids>" false`.
