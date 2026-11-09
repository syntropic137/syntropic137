# Mutation evidence for #701

All three are killed by `apps/syn-api/tests/test_api_cost_summary_top_lists.py`.

| Patch | Bug it re-introduces | Killing test |
|---|---|---|
| `01-top-models-unranked.patch` | `top_models` in insertion order, not by cost | `test_top_models_sums_each_model_across_executions_most_expensive_first` |
| `02-top-sessions-unranked.patch` | `top_sessions` in query order, not by cost | `test_top_sessions_are_most_expensive_first_and_bounded` |
| `03-top-sessions-unbounded.patch` | `top_sessions` not cut to `TOP_N` | `test_top_sessions_are_most_expensive_first_and_bounded` |
