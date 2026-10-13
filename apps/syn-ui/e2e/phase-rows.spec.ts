/**
 * Execution detail phase rows (feedback 1f70d3ab): a click anywhere on a
 * phase row opens that phase's session; inner links keep their own target;
 * a phase with no session yet is not a link and says why.
 */
import { expect, test } from './support/test'
import { isFixtures, isSkyline } from './support/env'
import { FIXTURE_IDS } from './support/routes'

test.skip(!isSkyline || !isFixtures, 'pins the fixture world on syn-ui')

test('clicking a phase row body opens its session', async ({ page }) => {
  await page.goto(`./executions/${FIXTURE_IDS.execution}`)
  const row = page.locator('ol > li', { has: page.getByRole('link', { name: /^Open the session for / }) }).first()
  await expect(row).toBeVisible()
  const link = row.getByRole('link', { name: /^Open the session for / })
  const target = await link.getAttribute('href')
  expect(target).toMatch(/\/sessions\/[^/]+$/)
  // The row's own padding, nowhere near the phase name or an inner link.
  const box = (await row.boundingBox())!
  await page.mouse.click(box.x + box.width / 2, box.y + 4)
  await expect(page).toHaveURL(new RegExp(`${target!.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`))
  await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible()
})

test('the phase row is reachable by keyboard and opens with Enter', async ({ page }) => {
  await page.goto(`./executions/${FIXTURE_IDS.execution}`)
  const link = page.getByRole('link', { name: /^Open the session for / }).first()
  await link.focus()
  await expect(link).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/sessions\/[^/]+$/)
})

test('an inner artifact link keeps its own target', async ({ page }) => {
  await page.goto(`./executions/${FIXTURE_IDS.execution}`)
  const artifact = page.locator('ol > li').getByRole('link', { name: /^Artifact from / }).first()
  await expect(artifact).toBeVisible()
  await artifact.click()
  await expect(page).toHaveURL(/\/artifacts\/[^/]+$/)
})
