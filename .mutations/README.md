# Mutation evidence for #897 slice C (repo and system cost from ExecutionCost)

Each patch reintroduces one bug. Each one was killed locally by the named test, and every named test passes on the clean head.

| Patch | Bug it reintroduces | Killed by |
|---|---|---|
| `01-system-cost-old-source.patch` | `/systems/{id}/cost` goes back to summing `RepoCost` payloads through `GetSystemCostHandler` | `apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestRepoAndSystemCostFromExecutionCost::test_partly_priced_is_a_lower_bound[system]` |
| `02-rollup-drops-unpriced-sum.patch` | the shared rollup keeps the last `unpriced_observation_count` instead of the sum | `apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestRepoAndSystemCostFromExecutionCost::test_every_unpriced_execution_counts_not_just_the_last[repo]` |
| `03-repo-cost-unscoped-read.patch` | `/repos/{id}/cost` reads every `ExecutionCost` row instead of the repo's correlated ids | `apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestRepoAndSystemCostFromExecutionCost::test_an_execution_outside_the_repo_adds_neither_money_nor_coverage` |

None of these tests needs Docker, so a run can pass `docker=false`:

```
just mutation-evidence 2330 "apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestRepoAndSystemCostFromExecutionCost::test_partly_priced_is_a_lower_bound apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestRepoAndSystemCostFromExecutionCost::test_every_unpriced_execution_counts_not_just_the_last apps/syn-api/tests/test_897_repo_and_system_cost_from_execution_cost.py::TestRepoAndSystemCostFromExecutionCost::test_an_execution_outside_the_repo_adds_neither_money_nor_coverage" false
```
