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
