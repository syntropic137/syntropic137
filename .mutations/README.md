# Mutation evidence for #2145 slice C

Killing tests: `apps/syn-api/tests/test_2145_1h_cache_writes_reach_the_cost_api.py`

| Patch | Bug re-introduced | Killed by |
|---|---|---|
| 01-session-dto-drops-1h.patch | `session_cost_to_data` drops the 1-hour share | `test_a_sessions_1h_writes_reach_the_response` |
| 02-execution-response-drops-1h.patch | `_execution_cost_to_api` drops the 1-hour share | `test_an_executions_1h_writes_reach_the_response` |
| 03-rollup-skips-1h.patch | `roll_up_costs` never sums the 1-hour share | `test_the_global_cost_sums_the_1h_share` |
| 04-events-session-cost-drops-1h.patch | `get_session_costs_endpoint` (`/events/sessions/{id}/costs`) drops the 1-hour share | `test_the_events_session_cost_carries_the_1h_share` |
