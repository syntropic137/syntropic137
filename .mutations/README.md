# Mutation evidence for #1843 item 6

Each patch is killed by `apps/syn-api/tests/test_endpoint_workflows_order_by.py`.

| Patch | Bug | Killed by |
|---|---|---|
| 01-sort-the-page-not-the-collection | the original defect: cut the page in default order, then sort it | `test_most_runs_first_is_global_and_numeric`, `test_name_order_is_global` |
| 02-runs-count-sorts-as-text | Postgres-style text ordering, "10" < "9" | `test_most_runs_first_is_global_and_numeric` |
| 03-tie-break-dropped | ties ordered by id descending instead of ascending | `test_most_runs_first_is_global_and_numeric` |
