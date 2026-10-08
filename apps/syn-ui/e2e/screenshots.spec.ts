/**
 * Visual baselines of the component reference pages, /dev/components and
 * /dev/patterns, at 1440px (`screenshots-1440`) and 390px (`screenshots-390`).
 * These pages are Skyline's component library: there is no Storybook.
 *
 * Opt-in with SYN_UI_SCREENSHOTS=1; only the `screenshots` job in
 * .github/workflows/syn-ui.yml sets it. Baselines live in e2e/baselines and
 * are Linux Chromium only, generated in CI (fonts differ on macOS, so a
 * local run writes *-darwin.png files that are git-ignored). Refreshing them
 * is described in design/README.md.
 */
import { isSkyline } from './support/env'
import { expect, open, test } from './support/test'

/** Same instant as FIXTURE_NOW in packages/syn-ui/data/src/fixtures/seed.ts, so relative times never drift. */
const FIXTURE_NOW = Date.UTC(2026, 9, 8, 9, 0, 0)

const PAGES = [
  { name: 'components', path: '/dev/components' },
  { name: 'patterns', path: '/dev/patterns' },
] as const

test.skip(!isSkyline, 'dev pages exist only in syn-ui')

for (const shot of PAGES) {
  test(`${shot.path} matches its baseline`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.clock.setFixedTime(FIXTURE_NOW)
    await open(page, shot.path)
    // Not aria-busy: the galleries show Skeleton and loading states on purpose.
    await page.waitForLoadState('networkidle')
    await page.evaluate(() => document.fonts.ready)
    await expect(page).toHaveScreenshot(`${shot.name}.png`, { fullPage: true, animations: 'disabled', caret: 'hide', maxDiffPixelRatio: 0.002 })
  })
}
