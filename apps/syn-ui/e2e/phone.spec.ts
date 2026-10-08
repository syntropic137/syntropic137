/**
 * Phone, 390px wide (the `phone` project): the floating dock and its More
 * sheet, the collapsed breadcrumb trail, and no horizontal page scroll on
 * any route.
 */
import { isSkyline } from './support/env'
import { DOCK, MORE, ROUTES } from './support/routes'
import { expect, horizontalOverflow, mainHeading, open, overflowingElements, pathFor, primaryNav, test, urlFor } from './support/test'

test.describe('every route at 390px', () => {
  for (const route of ROUTES) {
    test(`${route.name} fits the phone`, async ({ page }) => {
      const path = await pathFor(page, route)
      await open(page, path)
      // Let data and lazy parts settle before measuring.
      await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 10_000 }).catch(() => {})
      await page.waitForTimeout(300)

      const overflow = await horizontalOverflow(page)
      const culprits = overflow > 0 ? await overflowingElements(page) : []
      expect.soft(overflow, `no horizontal scroll (wider: ${culprits.join(', ')})`).toBeLessThanOrEqual(0)

      if (isSkyline) {
        const dock = primaryNav(page)
        await expect.soft(dock, 'one visible primary nav (the dock)').toHaveCount(1)
        await expect.soft(dock.getByRole('button', { name: 'More' }), 'dock More button').toBeVisible()
      }
    })
  }
})

test.describe('dock', () => {
  test.skip(!isSkyline, 'The React app has no phone dock')

  test('holds the four sections and More', async ({ page }) => {
    await open(page, '/')
    const dock = primaryNav(page)
    for (const label of DOCK) await expect.soft(dock.getByRole('link', { name: label, exact: true })).toBeVisible()
    await expect.soft(dock.getByRole('link')).toHaveCount(DOCK.length)
    await expect.soft(dock.getByRole('button', { name: 'More' })).toBeVisible()
    await expect.soft(dock.getByRole('link', { name: 'Overview', exact: true })).toHaveAttribute('aria-current', 'page')

    // The dock sits at the bottom of the screen and stays there.
    const box = await dock.boundingBox()
    const viewport = page.viewportSize()!
    expect.soft(box, 'dock box').not.toBeNull()
    if (box) {
      expect.soft(box.y + box.height, 'dock near the bottom edge').toBeGreaterThan(viewport.height - 80)
      expect.soft(box.x, 'dock inside the screen').toBeGreaterThanOrEqual(0)
      expect.soft(box.x + box.width, 'dock inside the screen').toBeLessThanOrEqual(viewport.width)
    }
  })

  test('dock items are touch sized', async ({ page }) => {
    await open(page, '/')
    const items = primaryNav(page).locator('a, button')
    const n = await items.count()
    for (let i = 0; i < n; i++) {
      const b = await items.nth(i).boundingBox()
      expect.soft(b && b.height >= 44, `dock item ${i} at least 44px tall`).toBe(true)
    }
  })

  test('navigates from the dock', async ({ page }) => {
    await open(page, '/')
    await primaryNav(page).getByRole('link', { name: 'Executions', exact: true }).click()
    await expect(page).toHaveURL(urlFor('/executions'))
    await expect(mainHeading(page)).toHaveText(/Executions/)
    await expect(primaryNav(page).getByRole('link', { name: 'Executions', exact: true })).toHaveAttribute('aria-current', 'page')
  })

  test('More opens the other sections and closes', async ({ page }) => {
    await open(page, '/')
    const more = primaryNav(page).getByRole('button', { name: 'More' })
    await more.click()
    await expect(more).toHaveAttribute('aria-expanded', 'true')
    const sheet = page.getByRole('dialog', { name: 'More sections' })
    await expect(sheet).toBeVisible()
    for (const label of MORE) await expect.soft(sheet.getByRole('link', { name: label, exact: true })).toBeVisible()

    // Escape closes it.
    await page.keyboard.press('Escape')
    await expect(sheet).toBeHidden()
    await expect(more).toHaveAttribute('aria-expanded', 'false')

    // A section in the sheet navigates and closes the sheet.
    await more.click()
    await sheet.getByRole('link', { name: 'Repos', exact: true }).click()
    await expect(page).toHaveURL(urlFor('/repos'))
    await expect(mainHeading(page)).toHaveText(/Repos/)
    await expect(sheet).toBeHidden()
  })
})

test.describe('breadcrumbs on a phone', () => {
  test.skip(!isSkyline, 'The React trail does not collapse')

  test('a deep trail collapses behind the ellipsis', async ({ page }) => {
    const runs = ROUTES.find((r) => r.name === 'workflow runs')!
    await open(page, await pathFor(page, runs))
    const trail = page.getByRole('navigation', { name: 'Breadcrumb' })
    await expect(trail).toBeVisible()
    const expand = trail.getByRole('button', { name: 'Show the full path' })
    await expect(expand).toBeVisible()
    // "Workflows" is the middle crumb: hidden until expanded.
    await expect(trail.getByRole('link', { name: 'Workflows', exact: true })).toBeHidden()
    await expand.click()
    await expect(trail.getByRole('link', { name: 'Workflows', exact: true })).toBeVisible()
    expect(await horizontalOverflow(page), 'expanded trail does not widen the page').toBeLessThanOrEqual(0)
  })
})
