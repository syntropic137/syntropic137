# Mutation evidence for #897 slice C, after verification round 1

The patches one level up (`.mutations/*.patch`) were written against
`d9fab274`. The round-1 fix rewrote the lines they touch, so they no longer
apply. They are left in place (never delete `.mutations/`, #2028); run this
directory instead. 01-03 are the same three bugs re-cut against the new head;
04-06 are the three defects verification found.

| Patch | Bug it reintroduces | Killed by |
|---|---|---|
| `01-system-cost-old-source.patch` | `/systems/{id}/cost` goes back to summing `RepoCost` payloads through `GetSystemCostHandler` | `apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestRepoAndSystemCostFromExecutionCost::test_partly_priced_is_a_lower_bound[system]` |
| `02-rollup-drops-unpriced-sum.patch` | the shared rollup keeps the last `unpriced_observation_count` instead of the sum | `apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestRepoAndSystemCostFromExecutionCost::test_every_unpriced_execution_counts_not_just_the_last[repo]` |
| `03-repo-cost-unscoped-read.patch` | `/repos/{id}/cost` reads every `ExecutionCost` row instead of the repo's correlated ids | `apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestRepoAndSystemCostFromExecutionCost::test_an_execution_outside_the_repo_adds_neither_money_nor_coverage` |
| `04-correlation-keeps-one-repo.patch` | an execution correlated with two repos keeps only the row the store returned last | `apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestProductionShapedCostRows::test_one_execution_in_two_repos_is_in_both_buckets_and_counted_once` (both orders) |
| `05-rollup-ignores-correlated-workflow.patch` | `cost_by_workflow` reads only `ExecutionCost.workflow_id`, which the production builders never set | `apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestProductionShapedCostRows::test_workflow_comes_from_the_correlation_when_the_cost_row_has_none` |
| `06-scoped-insights-filters-the-window.patch` | `/insights/cost?system_id=` filters the latest 10,000 executions instead of reading the system's ids | `apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestProductionShapedCostRows::test_system_and_insights_agree_when_newer_work_elsewhere_fills_the_window` |

None of these tests needs Docker:

```
just mutation-evidence 2330 "apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestRepoAndSystemCostFromExecutionCost::test_partly_priced_is_a_lower_bound apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestRepoAndSystemCostFromExecutionCost::test_every_unpriced_execution_counts_not_just_the_last apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestRepoAndSystemCostFromExecutionCost::test_an_execution_outside_the_repo_adds_neither_money_nor_coverage apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestProductionShapedCostRows" false .mutations/round-1/
```
