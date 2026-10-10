/**
 * Session detail Operations (feedback 18ec6964): newest first. The live
 * append path (execution stream invalidation, "N new") is unit tested in
 * skyline-core (live.test.ts) and data (invalidate.test.ts): fixtures mode
 * never opens an event stream.
 */
import { expect, test } from './support/test'
import { isFixtures, isSkyline } from './support/env'
import { FIXTURE_IDS } from './support/routes'

test.skip(!isSkyline || !isFixtures, 'pins the fixture world on syn-ui')

const seconds = (clock: string): number => {
  const m = /(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?/i.exec(clock)
  if (!m) return Number.NaN
  let h = Number(m[1]) % 12
  if ((m[4] ?? '').toUpperCase() === 'PM') h += 12
  if (!m[4]) h = Number(m[1])
  return h * 3600 + Number(m[2]) * 60 + Number(m[3] ?? 0)
}

test('operations read newest first', async ({ page }) => {
  await page.goto(`./sessions/${FIXTURE_IDS.session}`)
  const list = page.getByRole('list', { name: 'Operations, newest first' })
  await expect(list).toBeVisible()
  await expect(page.getByText(/recorded events?, newest first/)).toBeVisible()
  const rows = list.locator(':scope > li')
  const n = await rows.count()
  expect(n).toBeGreaterThan(1)
  const first = seconds((await rows.first().locator('span').first().textContent()) ?? '')
  const last = seconds((await rows.nth(n - 1).locator('span').first().textContent()) ?? '')
  expect(first).toBeGreaterThanOrEqual(last)
  // Nothing new arrived, so no "N new" pill.
  await expect(page.getByRole('button', { name: /new operations?$/ })).toHaveCount(0)
})
