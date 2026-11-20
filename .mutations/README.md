# Mutation evidence for #2145 B2b

All killers are in `packages/syn-domain/tests/contexts/test_2145_b2b_recorded_costs_price_1h_cache_writes.py`.

| Patch | Bug it re-introduces | Killed by |
|---|---|---|
| `01-helper-drops-1h-share.patch` | `CacheWrites.from_recorded` ignores the recorded 1-hour share, so every write is priced at the 5-minute rate (the bug on main) | `test_execution_cost_projection_prices_recorded_1h_writes[all-1h]`, `test_session_cost_projection_prices_recorded_1h_writes[all-1h]`, `test_execution_grouped_token_usage_prices_the_summed_1h_share[mixed]`, `test_session_grouped_rows_price_the_summed_1h_share[mixed]` |
| `02-execution-cost-version-unbumped.patch` | `ExecutionCostAdapter.VERSION` left at 1, so the deploy never replays the repriced read model | `test_cost_projection_versions_are_bumped_for_the_1h_reprice`. No generic guard pins projection VERSION to stored shape on main. This is a per-change pin, after the precedent in `test_1881_resume_lineage_reaches_the_execution_read_models.py`. |
| `03-helper-subtracts-nothing.patch` | the total is priced at the 5-minute rate AND the 1-hour share again (double counting) | the same four tests as 01 |

Run without Docker:

```
just mutation-evidence 2333 "packages/syn-domain/tests/contexts/test_2145_b2b_recorded_costs_price_1h_cache_writes.py" false
```

## Added in fix round 1 (verification finding 1)

| Patch | Bug it re-introduces | Killed by |
|---|---|---|
| `04-cost-rebuild-clears-nothing.patch` | the cost adapters' `clear_all_data` does nothing, so a VERSION mismatch replays onto the old running totals and counts every observation twice | all six cases of `test_version_rebuild_clears_old_totals_before_replaying` |
