# Mutation evidence for #701

The one patch is killed by `apps/syn-api/tests/test_api_cost_summary_top_lists.py`.

| Patch | Bug it re-introduces | Killing test |
|---|---|---|
| `01-top-models-unranked.patch` | `top_models` in insertion order, not by cost | `test_top_models_sums_each_model_across_executions_most_expensive_first` |
