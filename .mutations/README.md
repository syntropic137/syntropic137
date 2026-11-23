# Mutation evidence for #2341 follow-up (global /metrics)

Tests: `packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_2341_turn_sessions_are_bounded.py`
(no Docker needed: `just mutation-evidence <pr> "<that file>" false`).

| patch | restores | killed by |
|---|---|---|
| `01-every-day-reads-all-history.patch` | every per-day branch of the unpriced-turns read spans all history instead of its own UTC day, so each plans every chunk | `test_each_day_reads_only_its_own_sessions_and_chunk` |
| `02-evaluate-canonical-usage-twice.patch` | a second evaluation of the canonical usage CTEs only to list the unpriced sessions | `test_canonical_usage_is_evaluated_once_per_request[*]`, `test_a_priced_groups_sessions_never_leave_the_database`, `test_only_the_unpriced_groups_sessions_are_named` |

No patch for the concurrent global reads in `routes/metrics.py`: running them
in turn returns the same response, so that mutant is equivalent for every unit
test; its effect is latency, which the integration gate measures.
