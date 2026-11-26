# Mutation patches for PR #2377 (#1647 slice 1)

The tests these patches target are vitest, not pytest, so the
`mutation-evidence.yml` runner (pytest ids) cannot replay them. Each was applied
by hand, `pnpm fixtures:screenshot` re-run where the patch touches the fixture
module (so the drift test is not what kills it), and
`npx vitest run src/fixtures` plus `npx tsc -p tsconfig.app.json --noEmit` run
in `apps/syn-dashboard-ui`.

| Patch | Killed by |
| --- | --- |
| 01-drop-phase-cost-by-model-display | vitest: `shows the completed run populated, with the API cost text per model and per phase` (tsc does NOT catch it: the field is optional in `PhaseExecutionInfo`) |
| 02-drop-execution-cost-by-model-display | tsc TS2741 and the same vitest render test |
| 03-api-renames-execution-route | vitest: `answers only GET routes the OpenAPI spec serves` |
| 04-fixture-route-not-in-spec | tsc TS2345 and vitest: `answers only GET routes the OpenAPI spec serves` |

## Fix round 1: producer-fidelity patches (pytest)

Patches 05-09 change `screenshotFixtures.ts` AND carry the regenerated
`fixtures/screenshot.json`, so applying one is the whole mutant. Their target
is a pytest `unit` test, which the trusted runner can replay:
`apps/syn-api/tests/test_1647_screenshot_fixtures_mirror_the_producers.py`.

| Patch | Killed by |
| --- | --- |
| 05-heatmap-drops-cache-read | `test_the_heatmap_quotes_the_same_usage_as_the_global_metrics` |
| 06-running-progress-as-fraction | `test_phase_progress_and_plan_are_the_producers[running]` |
| 07-workflow-phase-cost-from-one-run | `test_workflow_phase_metrics_aggregate_every_execution` |
| 08-session-drops-cache-rates | `test_session_cost_and_cache_labels_are_the_producers[*]` (all six) |
| 09-skill-use-claims-observed | `test_skill_use_without_start_pins_is_unavailable[*]` (all three) |
