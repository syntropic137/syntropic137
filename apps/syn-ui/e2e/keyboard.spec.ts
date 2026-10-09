/**
 * Command palette and the app-wide keymap (skyline-core state/keymap.ts).
 * Skyline only: the React dashboard has neither.
 */
import type { Page } from '@playwright/test'
import { isFixtures, isSkyline } from './support/env'
import { expect, mainHeading, markWindow, open, test, urlFor, windowStillMarked } from './support/test'

test.skip(!isSkyline, 'Skyline keyboard layer')

/** Open a route and wait until the lazily loaded keyboard handler is live. */
async function openKeys(page: Page, path: string): Promise<void> {
  await open(page, path)
  await expect(page.locator('html')).toHaveAttribute('data-sky-keys', 'ready')
}

const palette = (page: Page) => page.getByRole('combobox', { name: 'Command palette' })

test.describe('command palette', () => {
  test('⌘K opens it, "exec" + Enter navigates to Executions', async ({ page }) => {
    await openKeys(page, '/')
    await markWindow(page)
    await page.keyboard.press('ControlOrMeta+k')
    await expect(palette(page)).toBeFocused()
    await palette(page).fill('exec')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(urlFor('/executions'))
    await expect(mainHeading(page)).toHaveText('Executions')
    await expect(palette(page)).toHaveCount(0)
    expect(await windowStillMarked(page), 'client-side navigation').toBe(true)
  })

  test('the search button opens it; Esc closes and returns focus', async ({ page }) => {
    await openKeys(page, '/workflows')
    const button = page.getByRole('button', { name: 'Search or jump to' }).first()
    await button.click()
    await expect(palette(page)).toBeFocused()
    await expect(page.getByRole('option', { name: /Executions/ })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(palette(page)).toHaveCount(0)
    await expect(button).toBeFocused()
    await expect(page).toHaveURL(urlFor('/workflows'))
  })

  test('lists recent executions from the cache', async ({ page }) => {
    await openKeys(page, '/')
    await page.keyboard.press('ControlOrMeta+k')
    await expect(page.getByRole('group', { name: 'Recent executions' }).getByRole('option').first()).toBeVisible()
  })
})

test.describe('keymap', () => {
  test('g e jumps to Executions', async ({ page }) => {
    await openKeys(page, '/')
    await markWindow(page)
    await page.keyboard.press('g')
    await page.keyboard.press('e')
    await expect(page).toHaveURL(urlFor('/executions'))
    expect(await windowStillMarked(page)).toBe(true)
  })

  test('? opens the shortcuts overlay with every binding and the help links', async ({ page }) => {
    await openKeys(page, '/')
    await page.keyboard.press('Shift+?')
    const dialog = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
    await expect(dialog).toBeVisible()
    await expect(dialog.locator('[data-binding="goto-executions"]')).toContainText('G')
    // Fixtures turn the feedback feature on, so its shortcuts are listed too.
    if (isFixtures) await expect(dialog.locator('[data-binding="feedback"]')).toBeVisible()
    await expect(dialog.getByRole('link', { name: 'Request a feature' })).toHaveAttribute('href', 'https://syntropic137.canny.io/')
    await expect(dialog.getByRole('link', { name: 'Report an issue' })).toHaveAttribute('href', /github\.com\/syntropic137\/syntropic137\/issues/)
    await expect(dialog.getByRole('link', { name: 'Documentation' })).toHaveAttribute('href', /^https:\/\//)
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
  })

  test('never captures keys while typing in an input', async ({ page }) => {
    await openKeys(page, '/executions')
    const search = page.getByRole('main').getByRole('searchbox').first()
    await search.click()
    await page.keyboard.type('g e j k ? /')
    await expect(search).toHaveValue('g e j k ? /')
    await expect(page).toHaveURL(urlFor('/executions'))
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })

  test('/ focuses the list search', async ({ page }) => {
    await openKeys(page, '/sessions')
    await page.locator('body').click({ position: { x: 1, y: 1 } })
    await page.keyboard.press('/')
    await expect(page.getByRole('main').getByRole('searchbox').first()).toBeFocused()
  })
})

test.describe('list rows', () => {
  for (const path of ['/executions', '/sessions', '/workflows', '/evals', '/artifacts', '/triggers', '/repos']) {
    test(`j / k move the active row on ${path}`, async ({ page }) => {
      await openKeys(page, path)
      const rows = page.locator('#sky-main [data-sky-row]')
      await expect(rows.first()).toBeVisible()
      await page.keyboard.press('j')
      await expect(rows.first()).toHaveAttribute('data-sky-active', '')
      if ((await rows.count()) > 1) {
        await page.keyboard.press('j')
        await expect(rows.nth(1)).toHaveAttribute('data-sky-active', '')
        await page.keyboard.press('k')
        await expect(rows.first()).toHaveAttribute('data-sky-active', '')
      }
      const outline = await rows.first().evaluate((el) => getComputedStyle(el).outlineStyle)
      expect(outline).toBe('solid')
    })
  }

  test('Enter opens the active execution and Backspace comes back', async ({ page }) => {
    await openKeys(page, '/executions')
    await expect(page.locator('#sky-main [data-sky-row]').first()).toBeVisible()
    await page.keyboard.press('j')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/executions\/[^/?]+/)
    await expect(page.getByRole('main').getByRole('heading', { level: 1 })).toBeVisible()
    await page.keyboard.press('Backspace')
    await expect(page).toHaveURL(urlFor('/executions'))
  })
})
