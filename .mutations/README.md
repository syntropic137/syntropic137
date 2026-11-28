# Mutation evidence for #1004 slice 3 (`sha_display`)

| Patch | Bug | Killed by |
|---|---|---|
| `01-display-is-full-sha.patch` | `sha_display` is the full SHA | `apps/syn-api/tests/test_1004_execution_detail_serves_commits_over_http.py` (`test_each_commit_serves_its_short_sha_for_display`, and the `_served` comparisons) |
| `02-none-displayed-as-empty.patch` | an unresolved `sha` displays as `""` | `apps/syn-api/tests/test_1004_execution_detail_serves_commits_over_http.py::test_an_unresolved_sha_displays_null_not_empty` |
| `03-ui-shows-raw-sha.patch` | syn-ui shows the raw `sha` | vitest, the lane runs it: `packages/syn-ui/skyline-core/src/screens/executions/commits.test.ts` |
