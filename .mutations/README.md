# Mutation evidence: #2145 slice B1 (PR #2329)

| Patch | Bug it re-introduces | Killed by |
|---|---|---|
| `01-ignore-ephemeral-1h.patch` | `CacheWrites.from_claude_usage` ignores `ephemeral_1h_input_tokens`, so every write is priced at the 5-minute rate | `packages/syn-domain/tests/contexts/workflows/execute_workflow/test_2145_a_live_turn_prices_1h_cache_writes.py::test_a_1h_cache_write_is_priced_at_the_1h_rate` (and `::test_a_mixed_turn_prices_each_tier_at_its_own_rate`) |
| `02-price-1h-at-5min-rate.patch` | `price_tokens` folds the 1-hour count into `cache_creation`, pricing it at the 5-minute rate | `packages/syn-shared/tests/test_price_tokens_1h_cache_write.py::test_price_tokens_prices_a_1h_write_at_the_1h_rate` (and the processor test above) |
| `03-accept-bool-counts.patch` | `_is_count` accepts `bool` (found in Codex pass 1) | `packages/syn-domain/tests/contexts/workflows/execute_workflow/test_2145_a_live_turn_prices_1h_cache_writes.py::test_a_malformed_split_is_priced_as_it_was_before` (cases 1h-bool, 5m-bool, total-bool) |

To dispatch (no Docker needed):

```
just mutation-evidence 2329 "packages/syn-domain/tests/contexts/workflows/execute_workflow/test_2145_a_live_turn_prices_1h_cache_writes.py::test_a_1h_cache_write_is_priced_at_the_1h_rate packages/syn-shared/tests/test_price_tokens_1h_cache_write.py::test_price_tokens_prices_a_1h_write_at_the_1h_rate packages/syn-domain/tests/contexts/workflows/execute_workflow/test_2145_a_live_turn_prices_1h_cache_writes.py::test_a_malformed_split_is_priced_as_it_was_before" false
```
