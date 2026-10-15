# Mutation evidence for #1552

| Patch | Bug re-introduced | Node ids that must kill it |
|---|---|---|
| `01-api-memory-default-ignores-concurrency.patch` | The API memory default is the fixed floor whatever the execution budget is | `packages/syn-shared/tests/test_execution_settings.py::TestTheApiMemoryDefaultIsDerivedFromConcurrency::test_a_budget_above_the_floor_raises_the_limit packages/syn-shared/tests/test_execution_settings.py::TestTheApiMemoryDefaultIsDerivedFromConcurrency::test_each_execution_past_the_floor_costs_its_allowance` |

Run: `just mutation-evidence <pr> "<node ids above>" false` (no Docker needed).
