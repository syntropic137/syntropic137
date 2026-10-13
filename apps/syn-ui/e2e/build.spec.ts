/**
 * The running build is visible without hunting (owner, Oct 8 2026): a mono
 * version under the wordmark at 1440, its full build on hover, and the same
 * rows in the phone More sheet at 390. Fixtures serve 0.33.2b23.
 */
import { isSkyline } from './support/env'
import { expect, open, primaryNav, test } from './support/test'

test.skip(!isSkyline, 'The React app shows its version in the sidebar')

test.describe('desktop, 1440', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test('the wordmark carries the API version and the tooltip the full build', async ({ page }) => {
    await open(page, '/')
    const mark = page.getByTestId('build-version').first()
    await expect(mark).toBeVisible()
    await expect(mark).toHaveText(/^v\d+\.\d+\.\d+/)
    await mark.hover()
    const tip = page.getByRole('tooltip')
    await expect(tip).toContainText('Commit')
    await expect(tip).toContainText('Deployed')
    await expect(tip).toContainText('UI')
  })

  test('the shortcuts overlay footer and the palette Help group carry it too', async ({ page }) => {
    await open(page, '/')
    await expect(page.getByTestId('build-version').first()).toBeVisible()
    await page.keyboard.press('Shift+?')
    const keys = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
    await expect(keys.getByTestId('build-block')).toContainText(/API\s*v\d+\.\d+\.\d+/)
    await page.keyboard.press('Escape')
    await page.keyboard.press('ControlOrMeta+k')
    await page.keyboard.type('version')
    await expect(page.getByRole('option', { name: /Version/ })).toContainText(/v\d+\.\d+\.\d+/)
  })
})

test.describe('phone, 390', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })

  test('the More sheet shows the build', async ({ page }) => {
    await open(page, '/')
    await primaryNav(page).getByRole('button', { name: 'More' }).click()
    const sheet = page.getByRole('dialog', { name: 'More sections' })
    const block = sheet.getByTestId('build-block')
    await expect(block).toBeVisible()
    await expect(block).toContainText(/API\s*v\d+\.\d+\.\d+/)
  })
})
