# Mutation evidence for #2145 slice B2a

Both patches are killed by
`packages/syn-domain/tests/contexts/workflows/execute_workflow/test_2145_the_token_usage_row_stores_1h_cache_writes.py::test_the_row_stores_the_1h_share_beside_the_unchanged_total`, which passes on the clean head.

| Patch | Bug re-introduced | Killed by (observed locally) |
|---|---|---|
| `01-collector-drops-1h-count.patch` | `_record_turn_usage_once` stops passing `cache_writes.one_hour` to the collector, so the row stores 0 1-hour writes | `test_the_row_stores_the_1h_share_beside_the_unchanged_total` (`assert 0 == 600`) |
| `02-row-stores-5m-as-total.patch` | the row's `cache_creation_tokens` is given `cache_writes.five_minute`, so the field stops meaning the total | `test_the_row_stores_the_1h_share_beside_the_unchanged_total` (`assert 400 == 1000`) |

Dispatch: `just mutation-evidence 2331 "packages/syn-domain/tests/contexts/workflows/execute_workflow/test_2145_the_token_usage_row_stores_1h_cache_writes.py::test_the_row_stores_the_1h_share_beside_the_unchanged_total" false`
