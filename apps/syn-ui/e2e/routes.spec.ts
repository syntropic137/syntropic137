/**
 * One test per route: heading, document title, breadcrumbs, the active nav
 * item, key fields (fixtures only) and no console errors. Checks are soft
 * so one run lists everything a screen is missing.
 */
import { isFixtures, isSkyline } from './support/env'
import { ROUTES } from './support/routes'
import { breadcrumbs, expect, mainHeading, open, pathFor, primaryNav, test } from './support/test'

for (const route of ROUTES) {
  test.describe(route.name, () => {
    test.setTimeout(60_000)
    test(`renders ${route.path}`, async ({ page }) => {
      const path = await pathFor(page, route)
      await open(page, path)

      // Heading
      const heading = isFixtures && route.fixtureHeading ? route.fixtureHeading : route.heading
      await expect.soft(mainHeading(page), 'page heading').toHaveText(heading, { timeout: 10_000 })
      expect.soft(await page.getByRole('heading', { level: 1 }).count(), 'exactly one h1').toBe(1)

      // Document title
      await expect.soft(page, 'document title').toHaveTitle(isSkyline && route.title ? route.title : /\S/)

      // Primary nav marks this section (Skyline uses aria-current; React has no equivalent).
      if (isSkyline) {
        const nav = primaryNav(page)
        await expect.soft(nav.getByRole('link', { name: route.nav, exact: true }), 'active nav item').toHaveAttribute('aria-current', 'page')
      }

      // Breadcrumbs
      if (route.crumbs.length === 0 && !route.current) {
        if (isSkyline) await expect.soft(page.getByRole('navigation', { name: 'Breadcrumb' }), 'no breadcrumbs on Overview').toHaveCount(0)
      }
      for (const crumb of route.crumbs) {
        const trail = breadcrumbs(page, crumb.label)
        const link = trail.getByRole('link', { name: crumb.label }).first()
        await expect.soft(link, `breadcrumb ${crumb.label}`).toBeVisible()
        await expect.soft(link, `breadcrumb ${crumb.label} href`).toHaveAttribute('href', crumb.href)
      }
      if (isSkyline) {
        const trail = breadcrumbs(page)
        if (route.crumbs.length || route.current) {
          await expect.soft(trail.getByRole('link', { name: 'Overview' }), 'breadcrumb home link').toBeVisible()
          const current = trail.locator('[aria-current="page"]')
          await expect.soft(current, 'current breadcrumb').toHaveCount(1)
          if (route.current) await expect.soft(current, 'current breadcrumb text').toHaveText(route.current)
        }
      }

      // Key fields
      if (isFixtures) {
        const main = page.getByRole('main')
        for (const text of route.fixtureText) {
          const loc = typeof text === 'string' ? main.getByText(text, { exact: false }) : main.getByText(text)
          await expect.soft(loc.first(), `key field ${String(text)}`).toBeVisible({ timeout: 5_000 })
        }
      }

      // Not stuck loading.
      await expect.soft(page.locator('[aria-busy="true"]'), 'nothing still loading').toHaveCount(0, { timeout: 10_000 })
    })
  })
}
