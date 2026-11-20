# Mutation evidence for #897 slice E (cost summaries report unpriced work)

All killers are in `apps/syn-api/tests/test_897_cost_summaries_report_unpriced.py`. Each one drives the real route with only the query or projection stubbed, and asserts on the JSON wire shape.

| Patch | Bug it re-introduces | Killed by |
|---|---|---|
| `01-cost-summary-drops-unpriced-sum.patch` | `GET /costs/summary` drops the unpriced count summed over its `ExecutionCost` rows and reports 0 | `test_cost_summary_sums_unpriced_counts_across_executions` (`assert 0 == 5`) |
| `02-cost-summary-plain-dollar-display.patch` | `GET /costs/summary` renders a plain dollar figure that ignores coverage | `test_cost_summary_of_partly_priced_work_is_a_lower_bound` (`'$1.25' == '>=$1.25 (partial)'`) |
| `03-session-costs-drop-unpriced-count.patch` | `GET /events/sessions/{id}/costs` drops `SessionCost.unpriced_observation_count` at the `TokenMetrics` hop | `test_session_costs_of_wholly_unpriced_work_say_unpriced` (`assert 0 == 3`) |
| `04-session-costs-plain-dollar-display.patch` | `GET /events/sessions/{id}/costs` renders a plain dollar figure that ignores coverage | `test_session_costs_of_partly_priced_work_are_a_lower_bound` (`'$0.42' == '>=$0.42 (partial)'`) |

Run without Docker:

```
just mutation-evidence 2334 "apps/syn-api/tests/test_897_cost_summaries_report_unpriced.py" false
```
