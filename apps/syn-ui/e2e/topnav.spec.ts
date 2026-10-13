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
