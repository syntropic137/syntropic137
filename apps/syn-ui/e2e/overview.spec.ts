/** Overview owner feedback (Oct 9 2026). */
import { isSkyline } from './support/env'
import { expect, open, test } from './support/test'

test.skip(!isSkyline, 'Skyline Overview')

// Feedback 9587ce0c: an All / 24h / 7d / 30d range on the Outcomes numbers,
// remembered per viewer.
test('Outcomes range narrows the counts and is remembered', async ({ page }) => {
  await open(page, '/')
  const card = page.getByRole('region', { name: 'Outcomes' })
  const range = card.getByRole('radiogroup', { name: 'Outcomes range' })
  await expect(range.getByRole('radio', { name: 'All' })).toBeChecked()
  const all = await card.getByRole('heading', { level: 2 }).textContent()
  expect(all).toMatch(/Outcomes · \d+ executions/)

  await range.getByRole('radio', { name: '24h' }).click()
  await expect(card.getByRole('heading', { level: 2 })).toHaveText(/Outcomes · \d+ in 24h/)
  const n24 = Number((await card.getByRole('heading', { level: 2 }).textContent())!.match(/(\d+) in/)![1])
  expect(n24).toBeLessThan(Number(all!.match(/(\d+) executions/)![1]))

  await page.reload()
  await expect(page.getByRole('region', { name: 'Outcomes' }).getByRole('radio', { name: '24h' })).toBeChecked()
})
