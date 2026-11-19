# Mutation evidence: #2145 slice A (PR #2326)

Each patch re-introduces one bug in `packages/syn-shared/src/syn_shared/pricing/__init__.py`.
Each passes on the clean head and is killed by the named tests.

| Patch | Bug | Killed by |
|---|---|---|
| `01-1h-write-at-5min-rate.patch` | 1-hour write tokens priced at `cache_creation_per_million` (5-min rate, today's under-pricing) | `packages/syn-shared/tests/test_cache_write_1h_pricing.py::test_opus_5_5_prices_a_1h_write_at_2x_input_not_the_5min_rate` |
| `02-1h-write-dropped-from-total.patch` | `cost_by_token_type` ignores `cache_creation_1h`, so 1-hour tokens never reach `cache_creation_usd` or `total` | `packages/syn-shared/tests/test_cache_write_1h_pricing.py::test_total_includes_the_1h_write` |

Dispatch (no Docker needed):

```
just mutation-evidence 2326 "packages/syn-shared/tests/test_cache_write_1h_pricing.py::test_opus_5_5_prices_a_1h_write_at_2x_input_not_the_5min_rate packages/syn-shared/tests/test_cache_write_1h_pricing.py::test_total_includes_the_1h_write" false
```

Locally (workspace rerun, not trusted evidence) each patch also failed
`test_1h_and_5min_writes_are_priced_each_at_its_own_rate`, `test_add_carries_the_1h_write`,
`test_allocated_to_apportions_the_1h_write` and `test_canonical_keeps_the_1h_write`.
