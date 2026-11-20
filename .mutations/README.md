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
| `05-summary-readers-drop-observed-1h.patch` | `observed_cache_creation_1h` ignores the turns' 1-hour share, so every reader that switches to a `session_summary` on completion reports 0 and the session's cache-write dollar split falls back to the 5-minute rate (verification finding 2) | 17 cases: the all-1h and mixed cases of `test_session_detail_keeps_the_1h_count_after_its_summary_arrives`, `test_session_list_keeps_the_1h_count_after_its_summary_arrives`, `test_execution_detail_keeps_the_1h_count_after_its_summary_arrives`, `test_execution_list_keeps_the_1h_count_after_its_summary_arrives`, and `test_session_cache_write_dollars_survive_an_authoritative_summary[reported-cost]` |


## Mixed finished and running sessions (#2333 review repair)

| Patch | Bug it re-introduces | Killed by |
|---|---|---|
| `06-summary-split-includes-running-sessions.patch` | Drops the session filter from the observed TTL split, attributing unfinished sessions' 1-hour writes to completed-session totals | `test_execution_summary_excludes_running_sessions_1h_writes` (both readers, both row orders) |

Patch 02 is regenerated against the current `ExecutionCostAdapter`, whose handler
subscriptions are inherited from `_CostProjectionAdapter`.
