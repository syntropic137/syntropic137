/**
 * Value parity with the React dashboard (scratchpad parity report,
 * 2026-10-09): each case pins a value the Svelte UI got wrong against the
 * fixture world, whose shapes mirror the live API.
 */
import { expect, test } from './support/test'
import { isFixtures, isSkyline } from './support/env'

test.skip(!isSkyline || !isFixtures, 'pins fixture values on syn-ui')

test('Overview Live commits lists commits from /events/recent, nested agent shape included', async ({ page }) => {
  await page.goto('./')
  const commits = page.getByRole('region', { name: 'Live commits' })
  await expect(commits.getByText('922a6b2')).toBeVisible()
  await expect(commits.getByText(/member-access specifier/)).toBeVisible()
  await expect(commits.getByText(/No git events yet/)).toHaveCount(0)
})

test('Workflow detail recent runs read the Executions list usage, failed phases included (#1843)', async ({ page }) => {
  await page.goto('./workflows/skills-matrix')
  const runs = page.locator('section', { has: page.getByRole('heading', { name: 'Recent runs' }) })
  // The failed run: 92,500 tokens on Executions; /runs alone would say 69.4k.
  await expect(runs.getByText('92.5k')).toBeVisible()
  await expect(runs.getByText('69.4k')).toHaveCount(0)
})

test('Workflow detail shows per-phase tokens and cost, sessions and artifacts (from /metrics?workflow_id=)', async ({ page }) => {
  await page.goto('./workflows/research-workflow')
  const main = page.locator('#sky-main')
  await expect(main.getByText('Sessions', { exact: true })).toBeVisible()
  await expect(main.getByText('Artifacts', { exact: true })).toBeVisible()
  await expect(main.getByText(/tok · \d+%/).first()).toBeVisible()
  // The fixture's running Research run: its phase cost still accrues.
  await expect(main.getByText(/^≥\$/).first()).toBeVisible()
})

test('Evals board cells show the latest run cost beside the latest verdict', async ({ page }) => {
  await page.goto('./evals')
  // shared-esp-stream under sonnet: runs $0.4963 (latest, PASS) and $0.4711; the median, shown before, is $0.48.
  const cell = page.locator('[data-cell="shared-esp-stream:eval-verify-pinned-sonnet-v1"]')
  await expect(cell).toHaveAttribute('aria-label', /: Pass, \$0\.50$/)
})
