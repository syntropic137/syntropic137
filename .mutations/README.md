# Mutation evidence for #1843 item 6

| Patch | Bug | Killed by |
|---|---|---|
| 04-page-local-sort-again | the original defect: store gets the default order, only the page is sorted by `order_by` | `apps/syn-api/tests/test_endpoint_workflows_order_by.py::test_most_runs_first_is_global_and_numeric`, `::test_name_order_is_global` |
| 05-postgres-orders-numbers-as-text | Postgres orders JSON numbers as text, "10" < "9" | `packages/syn-adapters/tests/test_postgres_query_builder.py::TestBuildQuery::test_order_by_json_numbers_numerically_first` |
| 06-memory-store-tie-break-dropped | in-memory store ties in insertion order, not by key | `packages/syn-adapters/tests/test_projection_stores.py::TestInMemoryProjectionStore::test_query_order_ties_break_by_key` |

01-03 targeted `_ordered()`/`_SORT_KEYS`, deleted in the fix round; removed by the verifier.
