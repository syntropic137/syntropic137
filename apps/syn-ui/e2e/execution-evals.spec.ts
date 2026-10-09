/**
 * Owner feedback 4df2bfc9 ("no way to tell if a run is an eval") and
 * 9a95d8f7 / cee46909 (every planned phase listed, progress counts the
 * same). Fixtures: the pr-review run an hour ago was launched by an eval.
 */
import { isFixtures, isSkyline } from './support/env'
import { expect, open, test } from './support/test'

test.skip(!isSkyline || !isFixtures, 'Skyline fixtures: eval marker and filter')

test('the Evals filter keeps only eval runs, each marked Eval', async ({ page }) => {
  await open(page, '/executions')
  const rows = page.locator('#sky-main [data-sky-row]')
  await expect(rows.first()).toBeVisible()
  const all = await rows.count()

  await page.getByRole('button', { name: 'Evals' }).click()
  await expect(page).toHaveURL(/[?&]eval=1/)
  await expect.poll(() => rows.count()).toBeLessThan(all)
  const n = await rows.count()
  expect(n).toBeGreaterThan(0)
  for (let i = 0; i < n; i++) await expect(rows.nth(i).getByText('Eval', { exact: true })).toBeVisible()

  // The detail links to the eval.
  await rows.first().getByRole('link').first().click()
  await expect(page.getByRole('link', { name: /^Eval: / })).toHaveAttribute('href', /\/evals\//)
})
