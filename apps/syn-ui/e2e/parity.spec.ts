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
