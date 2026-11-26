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
