/**
 * Fixture data for tests, Storybook-style previews and fixtures mode.
 * Import from '@syn137/syn-ui-data/fixtures'. The client loads the router on
 * its own in fixtures mode; app code never needs to import this.
 */
export { FIXTURE_NOW, ago, fakeId } from './seed'
export { WORKFLOWS, RUNS, phaseRuns, workflowOf, runOf } from './catalog'
export type { CatalogWorkflow, CatalogRun, CatalogPhase, CatalogPhaseRun } from './catalog'
export { EVAL_CASES, EVAL_VERIFIERS, EVALS } from './evals'
export { TRIGGERS } from './triggers'
export { REPOS } from './repos'
export { matchFixture, resolveFixture, route, notFound } from './router'
export type { FixtureRoute, FixtureRequest, FixtureHandler } from './router'
export { routes } from './routes'
