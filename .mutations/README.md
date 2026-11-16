# Mutation evidence for #1843 item 2

| Patch | Re-introduces | Killed by |
|---|---|---|
| `01-metrics-reads-artifact-counter.patch` | `GET /metrics` `total_artifacts` read from the dashboard_metrics running counter again | `apps/syn-api/tests/test_1843_metrics_totals_match_lists.py::test_total_artifacts_is_the_artifact_list_total`, `::test_total_artifacts_narrows_like_the_artifact_list` |
