/**
 * Evals at phone width: the verdict board scrolls inside its own box, so
 * neither the list nor an eval detail ever scrolls the page sideways.
 */
import { expect, test } from '@playwright/test'

const PAGES = ['/evals', '/evals/eval-stable-shared-esp-stream', '/evals/eval-shared-esp-stream-1']

test.describe('evals never scroll sideways', () => {
  test.use({ viewport: { width: 390, height: 844 } })
  for (const path of PAGES) {
    test(`${path} fits 390px`, async ({ page }) => {
      await page.goto(`.${path}`)
      await expect(page.locator('#sky-main h1').first()).toBeVisible()
      if (path === '/evals') await expect(page.locator('.sky-verdicts__grid')).toBeVisible()
      else await expect(page.locator('#sky-eval-runs')).toBeVisible()
      await expect(page.locator('#sky-main [aria-busy="true"]')).toHaveCount(0)
      const { scrollWidth, innerWidth } = await page.evaluate(() => ({ scrollWidth: document.scrollingElement!.scrollWidth, innerWidth: window.innerWidth }))
      expect(scrollWidth).toBeLessThanOrEqual(innerWidth)
    })
  }

  test('the board scrolls inside its own container', async ({ page }) => {
    await page.goto('./evals')
    const scroller = page.locator('.sky-verdicts__scroll')
    await expect(scroller).toBeVisible()
    const box = await scroller.evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth, overflow: getComputedStyle(el).overflowX }))
    expect(box.overflow).toBe('auto')
    expect(box.sw).toBeGreaterThan(box.cw)
    await expect(page.getByText(/Swipe the board sideways/)).toBeVisible()
  })
})
