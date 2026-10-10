/**
 * Overview IsoCity heatmap (Main and PhoneOverview boards): month stepping,
 * Now, the week strip jump, the day readout on hover, reduced motion and the
 * phone layout. Fixtures mode, with the clock pinned to the boards' Oct 9.
 */
import type { Page } from '@playwright/test'
import { isFixtures, isSkyline } from './support/env'
import { expect, open, test } from './support/test'

test.skip(!isSkyline || !isFixtures, 'Skyline fixtures: IsoCity')

async function openCity(page: Page) {
  await page.clock.setFixedTime(new Date('2026-10-09T12:00:00Z'))
  await open(page, '/')
  const scroll = page.getByRole('group', { name: 'Scroll through time' })
  await expect(scroll).toBeVisible()
  return scroll
}

test('month buttons step a calendar month, snapped to whole weeks; Now returns', async ({ page }) => {
  const scroll = await openCity(page)
  const now = scroll.getByRole('button', { name: 'Now' })
  await expect(scroll.getByText('Latest 14 weeks')).toBeVisible()
  await expect(page.getByText('Jul 6 – Oct 9, 2026')).toBeVisible()
  await expect(now).toHaveAttribute('aria-pressed', 'true')

  await scroll.getByRole('button', { name: 'One month back' }).click()
  await expect(scroll.getByText('1 month back')).toBeVisible()
  // Sep 9 is a Wednesday: the window ends on that week's Sunday.
  await expect(page.getByText('Jun 8 – Sep 13, 2026')).toBeVisible()
  await expect(now).toHaveAttribute('aria-pressed', 'false')

  await scroll.getByRole('button', { name: 'One month back' }).click()
  await expect(page.getByText('May 4 – Aug 9, 2026')).toBeVisible()
  await scroll.getByRole('button', { name: 'One month forward' }).click()
  await expect(scroll.getByText('1 month back')).toBeVisible()

  await now.click()
  await expect(scroll.getByText('Latest 14 weeks')).toBeVisible()
  await expect(scroll.getByRole('button', { name: 'One month forward' })).toBeDisabled()
})

test('the week strip jumps to that week, and arrow keys scroll when the city is focused', async ({ page }) => {
  const scroll = await openCity(page)
  await page.getByRole('button', { name: /^Week of Mar 2:/ }).click()
  await expect(scroll.getByText('7 months back')).toBeVisible()
  await expect(page.getByText('Dec 8, 2025 – Mar 15, 2026')).toBeVisible()

  await page.getByRole('group', { name: /^Activity city/ }).focus()
  await page.keyboard.press('ArrowRight')
  await expect(scroll.getByText('6 months back')).toBeVisible()
  await page.keyboard.press('End')
  await expect(scroll.getByText('Latest 14 weeks')).toBeVisible()
})

/** Move the mouse onto the middle of a block's top face: the pointer picks the visible surface, not a rectangle. */
async function pointAtTop(page: Page, date: string) {
  const box = await page.locator(`[data-date-block="${date}"] .sky-iso__top`).boundingBox()
  if (!box) throw new Error(`no block for ${date}`)
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
}

test('pointing at a block shows its day in the readout, failed count included', async ({ page }) => {
  await openCity(page)
  const readout = page.getByRole('status').filter({ hasText: 'Sessions' })
  const oct1 = page.getByRole('button', { name: 'Thu, Oct 1: 3 sessions, 2 failed' })
  await pointAtTop(page, '2026-10-01')
  await expect(oct1).toHaveAttribute('aria-pressed', 'true')
  await expect(readout).toContainText('Thu, Oct 1')
  await expect(readout).toContainText('2 failed')

  const aug28 = 'Fri, Aug 28: 43 sessions'
  // Its hit box sits partly behind a nearer block, as on the board; focus reaches it like a screen reader would.
  await page.getByRole('button', { name: aug28 }).focus()
  await expect(readout).toContainText('Fri, Aug 28')
  await expect(readout).not.toContainText('failed')
})

test('the Active days headline counts a fixed period, not the pages scrolled into view (codex review of #1856)', async ({ page }) => {
  const scroll = await openCity(page)
  const stat = page.locator('.sky-ov-stats > div').filter({ hasText: 'Active days' }).locator('dd')
  await expect(stat).not.toContainText('…')
  const before = await stat.textContent()
  for (let i = 0; i < 8; i++) await scroll.getByRole('button', { name: 'One month back' }).click()
  await expect(scroll.getByText('8 months back')).toBeVisible()
  await expect(page.locator('.sky-iso__load')).toHaveCount(0)
  expect(await stat.textContent()).toBe(before)
})

test('every week is a full column: today\'s week shows its future days as tiles (owner, Oct 10)', async ({ page }) => {
  await openCity(page)
  // Oct 9 is a Friday: Saturday and Sunday are future tiles, and Sunday is the front row.
  await expect(page.locator('.sky-iso__future').first()).toHaveAttribute('d', /^M.*Z.*M.*Z$/)
  await expect(page.locator('[data-date-block="2026-10-10"]')).toHaveCount(0)
})

test('stepping active days scrolls the window only when the day is out of view', async ({ page }) => {
  const scroll = await openCity(page)
  const prev = page.getByRole('group', { name: 'Active day' }).getByRole('button', { name: 'Previous active day' })
  await prev.click()
  await expect(scroll.getByText('Latest 14 weeks')).toBeVisible()
  // Step back until the day leaves the window (Jul 6 is its oldest week).
  for (let i = 0; i < 40; i++) {
    if ((await scroll.getByText('Latest 14 weeks').count()) === 0) break
    await prev.click()
  }
  await expect(scroll.getByText('1 month back')).toBeVisible()
})

test('reduced motion jumps instead of gliding', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const scroll = await openCity(page)
  await scroll.getByRole('button', { name: 'One month back' }).click()
  await expect(page.getByText('Jun 8 – Sep 13, 2026')).toBeVisible()
  await expect(page.locator('[data-gliding]')).toHaveCount(0)
  await expect(page.locator('[data-moving]')).toHaveCount(0)
})

test.describe('phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })
  test('shows 8 weeks, the 44px scroll buttons and the readout card', async ({ page }) => {
    const scroll = await openCity(page)
    await expect(scroll.getByText('Latest 8 weeks')).toBeVisible()
    const back = scroll.getByRole('button', { name: 'One month back' })
    expect((await back.boundingBox())?.height).toBeGreaterThanOrEqual(44)
    await back.click()
    await expect(scroll.getByText('1 month back')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Previous active day' })).toBeVisible()
    const width = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(width).toBeLessThanOrEqual(390)
  })
})
