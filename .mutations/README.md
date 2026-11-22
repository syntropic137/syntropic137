# Mutation evidence for #897 slice L

Tests: `apps/syn-api/tests/test_897_execution_detail_cost_display.py apps/syn-api/tests/test_1557_one_execution_budget.py::TestAQueuedStartIsVisible` (no Docker needed).

| Patch | Bug it re-introduces | Killed by |
|---|---|---|
| `01-phase-display-from-seed.patch` | phase `cost_display` built from the pre-enrichment seed, not `_enrich_costs`' value | `test_each_phase_reads_as_its_enriched_cost_not_its_seed` |
| `02-total-display-drops-coverage.patch` | execution `total_cost_display` ignores the unpriced count | `test_the_execution_total_reads_as_format_cost_renders_it` (partly / all unpriced) |
| `03-queued-start-reads-free.patch` | a queued start reports `$0.00` instead of an em dash | `TestAQueuedStartIsVisible` |

Locally (workspace, no Docker) each patch was applied and the named tests failed; reverted, they pass.
