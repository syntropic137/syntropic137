/**
 * Moving around: primary nav, list to detail and back by breadcrumb,
 * browser history, redirects and the not-found page. All navigation must
 * stay client-side (no full reload).
 */
import { isSkyline } from './support/env'
import { ROUTES, SECTIONS } from './support/routes'
import {
  arrived,
  breadcrumbs,
  esc,
  expect,
  firstDetailId,
  mainHeading,
  markWindow,
  open,
  pathFor,
  primaryNav,
  test,
  urlFor,
  windowStillMarked,
} from './support/test'

test.describe('primary nav', () => {
  for (const s of SECTIONS) {
    test(`goes to ${s.path}`, async ({ page }) => {
      // Start somewhere else so the click is a real navigation.
      await open(page, s.path === '/repos' ? '/' : '/repos')
      await markWindow(page)
      await primaryNav(page).getByRole('link', { name: s.label }).click()
      await expect(page).toHaveURL(urlFor(s.path))
      await expect(mainHeading(page)).toHaveText(s.heading)
      expect(await windowStillMarked(page), 'client-side navigation (no reload)').toBe(true)
    })
  }
})

test.describe('list to detail and back', () => {
  for (const route of ROUTES.filter((r) => r.id && r.listPath && !r.path.endsWith('/runs'))) {
    test(`${route.listPath} -> ${route.path}`, async ({ page }) => {
      const listPath = route.listPath!
      const kind = route.id!
      await open(page, listPath)
      const id = await firstDetailId(page, kind)
      expect(id, `a link to a ${kind} on ${listPath}`).not.toBeNull()
      await markWindow(page)
      const listHeading = (await mainHeading(page).textContent())?.trim() ?? null
      await page.locator(`a[href$="${listPath}/${encodeURIComponent(id!)}"]`).first().click()
      await expect(page).toHaveURL(urlFor(`${listPath}/${encodeURIComponent(id!)}`))
      // The detail's own heading: its breadcrumb trail is final from here on.
      await arrived(page, listHeading)
      expect(await windowStillMarked(page), 'client-side navigation (no reload)').toBe(true)

      // Back to the list through the breadcrumb.
      const parent = route.crumbs[0]
      const back = breadcrumbs(page, parent.label).getByRole('link', { name: parent.label }).first()
      const backHref = await back.getAttribute('href')
      await back.click()
      await expect(page).toHaveURL(new RegExp(`${esc(backHref ?? listPath)}/?$`))
      await expect(mainHeading(page)).toBeVisible()

      // And forward again with the browser.
      await page.goBack()
      await expect(page).toHaveURL(urlFor(`${listPath}/${encodeURIComponent(id!)}`))
      await page.goBack()
      await expect(page).toHaveURL(urlFor(listPath))
      await expect(mainHeading(page)).toBeVisible()
    })
  }
})

test('workflow detail links to its runs', async ({ page }) => {
  const detail = ROUTES.find((r) => r.name === 'workflow detail')!
  const path = await pathFor(page, detail)
  await open(page, path)
  const runs = page.locator(`a[href$="${path}/runs"]`).first()
  await expect(runs, 'link to the runs page').toBeVisible()
  await runs.click()
  await expect(page).toHaveURL(urlFor(`${path}/runs`))
  await expect(mainHeading(page)).toBeVisible()
})

test('workflow runs breadcrumb returns to the workflow', async ({ page }) => {
  const runs = ROUTES.find((r) => r.name === 'workflow runs')!
  const path = await pathFor(page, runs)
  await open(page, path)
  const workflowPath = path.replace(/\/runs$/, '')
  const link = breadcrumbs(page, /^Workflows$/).locator(`a[href$="${workflowPath}"]`)
  await expect(link, 'breadcrumb link to the workflow').toBeVisible()
  await link.click()
  await expect(page).toHaveURL(urlFor(workflowPath))
})

test('Overview has no breadcrumbs and the home crumb leads there', async ({ page }) => {
  await open(page, '/executions')
  const home = isSkyline ? breadcrumbs(page).getByRole('link', { name: 'Overview' }) : page.locator('nav a[href="/"]').last()
  await home.click()
  await expect(page).toHaveURL(urlFor('/'))
  if (isSkyline) await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toHaveCount(0)
})

test.describe('Skyline only', () => {
  test.skip(!isSkyline, 'React keeps /insights and has no not-found page')

  test('/insights redirects to Overview', async ({ page }) => {
    await page.goto('insights/costs')
    await expect(page).toHaveURL(urlFor('/'))
    await expect(page).toHaveTitle(/Overview/)
  })

  test('back to a list renders cached data on the first frame (ADR-074 query cache)', async ({ page }) => {
    await open(page, '/executions')
    const id = await firstDetailId(page, 'execution')
    expect(id, 'a link to an execution').not.toBeNull()
    const listHeading = (await mainHeading(page).textContent())?.trim() ?? null
    await page.locator(`a[href$="/executions/${encodeURIComponent(id!)}"]`).first().click()
    await expect(page).toHaveURL(urlFor(`/executions/${encodeURIComponent(id!)}`))
    // The detail itself, not the list still on screen while its chunk loads.
    await arrived(page, listHeading)
    // Count every skeleton inserted from here on: a cache hit never mounts one.
    await page.evaluate(() => {
      const w = window as unknown as { skeletonsSeen: number }
      w.skeletonsSeen = 0
      new MutationObserver((records) => {
        for (const r of records)
          for (const n of r.addedNodes)
            if (n instanceof Element && (n.matches('.sky-skeleton') || n.querySelector('.sky-skeleton'))) w.skeletonsSeen++
      }).observe(document.body, { childList: true, subtree: true })
    })
    await page.goBack()
    await expect(page).toHaveURL(urlFor('/executions'))
    await expect(page.locator(`a[href$="/executions/${encodeURIComponent(id!)}"]`).first()).toBeVisible()
    expect(await page.evaluate(() => (window as unknown as { skeletonsSeen: number }).skeletonsSeen), 'skeletons mounted on the way back').toBe(0)
  })

  test('unknown path shows not found', async ({ page }) => {
    await page.goto('no-such-page')
    await expect(mainHeading(page)).toBeVisible()
    await expect(page).toHaveTitle(/not found/i)
    await expect(page.getByRole('link', { name: new RegExp(esc('Overview')) }).first()).toBeVisible()
  })
})
