# Mutation evidence for #2341 (PR #2349)

| Patch | Bug it re-introduces | Killed by |
|---|---|---|
| `01-restore-unbounded-array.patch` | `_TOTALS_QUERY` aggregates `ARRAY_AGG(session_id)` over every summary-less session of every group again | `packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_2341_turn_sessions_are_bounded.py::test_a_priced_groups_sessions_never_leave_the_database` |
| `02-count-zero-usage-turns.patch` | drops `AND NOT zero_usage_group_by()` from `_UNPRICED_TURNS_DAY`, so zero-token turns count as unpriced observations | `packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_897_canonical_totals_coverage.py::test_zero_token_turns_are_not_counted` |
| `03-one-unbounded-span-per-day.patch` | every per-day branch of `_UNPRICED_TURNS_QUERY` reads all history instead of its own UTC day, so each branch plans every chunk again | `packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_2341_turn_sessions_are_bounded.py::test_each_day_reads_only_its_own_sessions_and_chunk` |

None needs Docker: `just mutation-evidence 2349 "<the three ids above>" false`.
Against TimescaleDB, `apps/syn-api/tests/integration/test_metrics_summary_less_sessions_at_scale.py` also asserts the exact `unpriced_observation_count` that patch 02 inflates.
