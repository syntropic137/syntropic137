# Mutation evidence for #897 slice A (PR #2324)

| Patch | Bug re-introduced | Killed by |
|---|---|---|
| `01-drop-unpriced-sum.patch` | `_aggregate_costs` stops summing `unpriced_observation_count` (the pre-fix behaviour) | `apps/syn-api/tests/test_897_insights_cost_reports_unpriced_work.py::TestInsightsCostReportsUnpricedWork::test_a_wholly_unpriced_fleet_is_unpriced_not_zero_dollars` (and `test_a_partly_unpriced_fleet_is_a_lower_bound`) |
| `02-display-plain-dollars.patch` | `total_cost_display` rendered as a plain dollar amount, ignoring coverage | `apps/syn-api/tests/test_897_insights_cost_reports_unpriced_work.py::TestInsightsCostReportsUnpricedWork::test_a_partly_unpriced_fleet_is_a_lower_bound` (and `test_a_wholly_unpriced_fleet_is_unpriced_not_zero_dollars`) |
| `03-overwrite-unpriced-sum.patch` | coverage from the second and later unpriced records is dropped (the verifier's surviving mutant) | `apps/syn-api/tests/test_897_insights_cost_reports_unpriced_work.py::TestInsightsCostReportsUnpricedWork::test_every_unpriced_execution_counts_not_just_the_first` |

No Docker needed:

```
just mutation-evidence 2324 "apps/syn-api/tests/test_897_insights_cost_reports_unpriced_work.py::TestInsightsCostReportsUnpricedWork::test_a_wholly_unpriced_fleet_is_unpriced_not_zero_dollars apps/syn-api/tests/test_897_insights_cost_reports_unpriced_work.py::TestInsightsCostReportsUnpricedWork::test_a_partly_unpriced_fleet_is_a_lower_bound apps/syn-api/tests/test_897_insights_cost_reports_unpriced_work.py::TestInsightsCostReportsUnpricedWork::test_every_unpriced_execution_counts_not_just_the_first" false
```
