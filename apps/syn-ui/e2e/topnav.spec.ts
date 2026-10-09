/** The desktop top bar stays on one row (owner tweak, Oct 8 2026). */
import { isSkyline } from './support/env'
import { expect, open, test } from './support/test'

test.skip(!isSkyline, 'Skyline top bar')

for (const width of [1280, 1440]) {
  test(`top bar is one row at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await open(page, '/executions')
    const header = page.locator('.sky-topnav')
    const capsule = page.locator('.sky-capsule')
    const h = (await header.boundingBox())!
    const c = (await capsule.boundingBox())!
    // One row: the bar (capsule plus its padding) stays under two capsules tall.
    expect(h.height).toBeLessThan(c.height * 2)
    // And nothing spills sideways out of it.
    expect(await header.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(0)
  })
}

// Feedback 1117bb69: the wordmark uses the rebrand blue cube. Its background is
// baked in, so the tile must be rounded, never a hard square on the dark bar.
test('wordmark shows the rebrand mark as a rounded tile', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page, '/executions')
  const mark = page.locator('.sky-topnav .sky-wordmark__mark')
  await expect(mark).toBeVisible()
  const info = await mark.evaluate((el) => {
    const img = el as HTMLImageElement
    return { w: img.naturalWidth, h: img.naturalHeight, radius: parseFloat(getComputedStyle(img).borderTopLeftRadius) }
  })
  // The cropped landing mark is 320px square: crisp at 26px and at 2x.
  expect(info.w).toBe(320)
  expect(info.h).toBe(320)
  expect(info.radius).toBeGreaterThan(0)
})
