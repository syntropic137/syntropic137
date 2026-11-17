/**
 * Copy works without the async Clipboard API (#742). A self-hosted dashboard on
 * plain http has no `navigator.clipboard`, so every copy takes the
 * execCommand fallback. The command palette copies while its native modal is
 * still open, where a textarea outside the dialog is inert: Chromium then
 * reports success and leaves the clipboard unchanged. This reads the real
 * clipboard from a second page that keeps the Clipboard API.
 * Skyline only: the React dashboard has no command palette.
 */
import type { BrowserContext, Page } from '@playwright/test'
import { isSkyline } from './support/env'
import { expect, open, test } from './support/test'

test.skip(!isSkyline, 'Skyline command palette')

const SENTINEL = 'sentinel-before-copy'

async function clipboardReader(context: BrowserContext, origin: string): Promise<Page> {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin })
  const reader = await context.newPage()
  await reader.goto(origin)
  await reader.evaluate((text) => navigator.clipboard.writeText(text), SENTINEL)
  return reader
}

const readClipboard = (reader: Page) => reader.evaluate(() => navigator.clipboard.readText())

test('the command palette copies the page for an agent without the Clipboard API', async ({ page, context, baseURL }) => {
  const origin = new URL(baseURL ?? page.url()).origin
  const reader = await clipboardReader(context, origin)
  await page.addInitScript(() => {
    Object.defineProperty(Navigator.prototype, 'clipboard', { configurable: true, get: () => undefined })
  })
  await open(page, '/')
  await expect(page.locator('html')).toHaveAttribute('data-sky-keys', 'ready')
  expect(await page.evaluate(() => typeof navigator.clipboard)).toBe('undefined')

  await page.keyboard.press('ControlOrMeta+k')
  const palette = page.getByRole('combobox', { name: 'Command palette' })
  await expect(palette).toBeFocused()
  await palette.fill('Copy page for an agent')
  await page.keyboard.press('Enter')
  await expect(palette).toHaveCount(0)

  await expect.poll(() => readClipboard(reader)).not.toBe(SENTINEL)
  const copied = await readClipboard(reader)
  expect(copied).toMatch(/^Syntropic137 page: /)
  expect(copied).toContain(`URL: ${page.url()}`)
})
