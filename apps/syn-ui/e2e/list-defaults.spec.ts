/**
 * Executions and Sessions open on the last 24 hours (owner tweak, Oct 8
 * 2026); All and the other windows stay one click away.
 */
import { isSkyline } from './support/env'
import { expect, open, test, urlFor } from './support/test'

test.skip(!isSkyline, 'Skyline list defaults')

for (const path of ['/executions', '/sessions']) {
  test(`${path} defaults to 24h and All stays selectable`, async ({ page }) => {
    await open(page, path)
    const windows = page.getByRole('radiogroup', { name: 'Time window' })
    await expect(windows.getByRole('radio', { name: '24h' })).toHaveAttribute('aria-checked', 'true')
    const rows = page.locator('#sky-main [data-sky-row]')
    await expect(rows.first()).toBeVisible()
    // Sessions virtualise their rows, so count by the hero's server total there.
    const total = async () => (path === '/sessions' ? Number(await page.locator('.sky-sessions__hero').getAttribute('data-total')) : rows.count())
    const recent = await total()

    await windows.getByRole('radio', { name: 'All' }).click()
    await expect(page).toHaveURL(/[?&]window=all/)
    await expect(windows.getByRole('radio', { name: 'All' })).toHaveAttribute('aria-checked', 'true')
    await expect.poll(total).toBeGreaterThan(recent)

    // Back to the default: the param drops out of the URL.
    await windows.getByRole('radio', { name: '24h' }).click()
    await expect(page).toHaveURL(urlFor(path))
    await expect(page).not.toHaveURL(/window=/)
  })
}
