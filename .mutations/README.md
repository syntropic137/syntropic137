# Mutation evidence for #2341 follow-up (global /metrics)

Tests: `packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_2341_turn_sessions_are_bounded.py`
(no Docker needed: `just mutation-evidence <pr> "<that file>" false`).

| patch | restores | killed by |
|---|---|---|
| `01-every-day-reads-all-history.patch` | every per-day branch of the unpriced-turns read spans all history instead of its own UTC day, so each plans every chunk | `test_each_day_reads_only_its_own_sessions_and_chunk` |
| `02-evaluate-canonical-usage-twice.patch` | a second evaluation of the canonical usage CTEs only to list the unpriced sessions | `test_canonical_usage_is_evaluated_once_per_request[*]`, `test_a_priced_groups_sessions_never_leave_the_database`, `test_only_the_unpriced_groups_sessions_are_named` |
| `03-global-reads-in-turn.patch` | the four global reads awaited one after another instead of together | `apps/syn-api/tests/test_2341_global_metrics_reads_run_together.py::test_the_global_reads_are_all_in_flight_at_once` |

Patch 03's test lives in `apps/syn-api/tests/`; pass both test files to `just mutation-evidence`.
