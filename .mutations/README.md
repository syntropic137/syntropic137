# Mutation evidence for #2341 follow-up (global /metrics)

Tests: `packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_2341_turn_sessions_are_bounded.py`
(no Docker needed: `just mutation-evidence <pr> "<that file>" false`).

| patch | restores | killed by |
|---|---|---|
| `01-restore-per-day-union-all.patch` | one `UNION ALL` branch per UTC day, each naming `agent_events`, in the unpriced-turns read | `test_the_turns_read_names_agent_events_once_whatever_the_day_count[1,16,91]`, `test_each_session_day_is_read_within_its_own_day` |
| `02-evaluate-canonical-usage-twice.patch` | a second evaluation of the canonical usage CTEs only to list the unpriced sessions | `test_canonical_usage_is_evaluated_once_per_request[*]`, `test_a_priced_groups_sessions_never_leave_the_database`, `test_only_the_unpriced_groups_sessions_are_named` |
