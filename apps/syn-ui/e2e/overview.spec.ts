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

// Feedback 443e9c0a: a "needs a look" run the viewer opened stays hidden on
// return, behind a muted "N seen · show".
test('needs-a-look chips disappear once opened', async ({ page }) => {
  await open(page, '/')
  const chips = page.getByRole('list', { name: 'Runs that need a look' }).getByRole('link')
  await expect(chips.first()).toBeVisible()
  const target = (await chips.first().getAttribute('href'))!
  await chips.first().click()
  await expect(page).toHaveURL(new RegExp(target.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$'))
  await page.goBack()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.locator(`a.sky-ov-chip[href="${target}"]`)).toHaveCount(0)
  const toggle = page.getByRole('button', { name: '1 seen · show' })
  await expect(toggle).toBeVisible()
  await toggle.click()
  await expect(page.locator(`a.sky-ov-chip[href="${target}"]`)).toBeVisible()
  await expect(page.getByRole('button', { name: '1 seen · hide' })).toBeVisible()

  // Remembered per viewer across a reload.
  await page.reload()
  await expect(page.getByRole('button', { name: '1 seen · show' })).toBeVisible()
  await expect(page.locator(`a.sky-ov-chip[href="${target}"]`)).toHaveCount(0)
})

test('needs-a-look still works when storage throws', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', { get: () => { throw new Error('blocked') } })
  })
  await open(page, '/')
  await expect(page.getByRole('list', { name: 'Runs that need a look' }).getByRole('link').first()).toBeVisible()
  await expect(page.getByRole('region', { name: 'Outcomes' }).getByRole('radio', { name: 'All' })).toBeChecked()
})
