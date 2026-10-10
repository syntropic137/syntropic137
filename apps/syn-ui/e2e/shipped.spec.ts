/** Overview "Shipped by agents" (Main and PhoneOverview boards), fixtures world. */
import { isFixtures, isSkyline } from './support/env'
import { expect, open, test } from './support/test'

test.skip(!isSkyline || !isFixtures, 'Skyline fixtures: shipped-by-agents sample')

const BOARD = [
  ['Commits', '1,204', '+38%'],
  ['PRs opened', '73', '+24%'],
  ['PRs merged', '61', '+27%'],
  ['Merge rate', '84%', '+5 pts'],
  ['Repos touched', '9', '+3'],
] as const

test('five tiles render the board totals, deltas and 14-bar sparklines', async ({ page }) => {
  await open(page, '/')
  const block = page.getByRole('region', { name: 'Shipped by agents, last 14 days' })
  await expect(block.getByText('Last 14 days, vs the 14 before')).toBeVisible()
  await expect(block.getByRole('link', { name: 'by workflow →' })).toHaveAttribute('href', /\/workflows$/)
  const tiles = block.getByRole('listitem')
  await expect(tiles).toHaveCount(5)
  for (const [i, [label, total, delta]] of BOARD.entries()) {
    const tile = tiles.nth(i)
    await expect(tile).toContainText(label)
    await expect(tile.locator('.sky-ov-shipped__total')).toHaveText(total)
    await expect(tile.locator('.sky-ov-shipped__delta')).toHaveText(delta)
    await expect(tile.locator('.sky-ov-shipped__delta')).toHaveAttribute('data-tone', 'better')
    await expect(tile.locator('rect')).toHaveCount(14)
  }
})

test('a tile the server cannot answer says so', async ({ page }) => {
  await page.addInitScript(() => {
    ;(globalThis as { synFixtureShippedUnavailable?: string[] }).synFixtureShippedUnavailable = ['prs_opened']
  })
  await open(page, '/')
  const tiles = page.getByRole('region', { name: 'Shipped by agents, last 14 days' }).getByRole('listitem')
  await expect(tiles.nth(1)).toContainText('PRs opened')
  await expect(tiles.nth(1)).toContainText('Not available on this server')
  await expect(tiles.nth(1).locator('.sky-ov-shipped__total')).toHaveCount(0)
  await expect(tiles.nth(0).locator('.sky-ov-shipped__total')).toHaveText('1,204')
})

test('no page overflow at phone width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await open(page, '/')
  await expect(page.getByRole('region', { name: 'Shipped by agents, last 14 days' })).toBeVisible()
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({ scrollWidth: document.scrollingElement!.scrollWidth, innerWidth: window.innerWidth }))
  expect(scrollWidth).toBeLessThanOrEqual(innerWidth)
})
