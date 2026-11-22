# Mutation evidence for #2341 (PR #2349)

| Patch | Bug it re-introduces | Killed by |
|---|---|---|
| `01-restore-unbounded-array.patch` | `_TOTALS_QUERY` aggregates `ARRAY_AGG(session_id)` over every summary-less session of every group again | `packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_2341_turn_sessions_are_bounded.py::test_a_priced_groups_sessions_never_leave_the_database` |
| `02-count-zero-usage-turns.patch` | drops `AND NOT zero_usage_group_by()` from `_UNPRICED_TURNS_QUERY`, so zero-token turns count as unpriced observations | `packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_897_canonical_totals_coverage.py::test_zero_token_turns_are_not_counted` |

Neither needs Docker: `just mutation-evidence 2349 "<the two ids above>" false`.
Against TimescaleDB, `apps/syn-api/tests/integration/test_metrics_summary_less_sessions_at_scale.py` also asserts the exact `unpriced_observation_count` that patch 02 inflates.
