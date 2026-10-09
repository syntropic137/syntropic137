/**
 * Feedback bubble (#1385): in fixtures mode the API turns `ui_feedback` on, so
 * the bubble shows bottom right. Covers the shortcut, in-dialog type and
 * priority hotkeys, element picking, an uploaded screenshot (a stub PNG; the
 * html2canvas capture is exercised live, not here) and the submit.
 * Skyline only (the React widget is a different control) and fixtures only
 * (never file real feedback from a test).
 */
import { isFixtures, isSkyline } from './support/env'
import { expect, open, test } from './support/test'

test.skip(!isSkyline || !isFixtures, 'Skyline feedback bubble, fixtures mode only')

/** A valid 1x1 PNG: the fixture checks the declared type, the API checks the magic bytes. */
const PNG_1X1 = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64')

test('bubble menu opens a note; title is required', async ({ page }) => {
  await open(page, '/executions')
  const bubble = page.getByRole('button', { name: 'Send feedback' })
  await bubble.click()
  await page.getByRole('menuitem', { name: /Quick note/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Send feedback' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByTestId('feedback-attached')).toContainText('/executions')
  await dialog.getByRole('button', { name: 'Send feedback' }).click()
  await expect(dialog.getByText('Add a title.')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})

test('f opens, hotkeys pick type and priority, pick an element, upload, submit', async ({ page }) => {
  await open(page, '/executions')
  await expect(page.getByRole('button', { name: 'Send feedback' })).toBeVisible()
  await page.locator('#sky-main').focus()
  await page.keyboard.press('f')
  const dialog = page.getByRole('dialog', { name: 'Send feedback' })
  await expect(dialog).toBeVisible()

  // Single-key hotkeys while focus is not in a text field.
  await page.keyboard.press('u')
  await page.keyboard.press('3')
  await expect(dialog.getByTestId('feedback-type-ui_ux')).toHaveAttribute('aria-checked', 'true')
  await expect(dialog.getByTestId('feedback-priority-high')).toHaveAttribute('aria-checked', 'true')

  // Element picker: E, hover, click; the chip names what was pinned.
  await page.keyboard.press('e')
  const picker = page.getByTestId('feedback-picker')
  await expect(picker).toBeVisible()
  const heading = page.locator('#sky-main h1').first()
  const box = await heading.boundingBox()
  if (!box) throw new Error('no heading to pick')
  await page.mouse.move(box.x + 8, box.y + box.height / 2)
  await page.mouse.click(box.x + 8, box.y + box.height / 2)
  await expect(picker).toBeHidden()
  await expect(dialog.getByTestId('feedback-element')).toContainText('h1')

  // Esc in the picker cancels and returns to the draft.
  await dialog.getByRole('button', { name: 'Re-pick' }).click()
  await expect(picker).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByTestId('feedback-element')).toContainText('h1')

  await dialog.getByTestId('feedback-file').setInputFiles({ name: 'stub.png', mimeType: 'image/png', buffer: PNG_1X1 })
  await expect(dialog.getByRole('img', { name: 'Screenshot 1' })).toBeVisible()

  await dialog.getByLabel('Title').fill('syn-ui feedback bubble e2e')
  await dialog.getByRole('button', { name: 'Send feedback' }).click()
  await expect(dialog.getByRole('status')).toContainText('with 1 screenshot')
  await expect(dialog.getByTestId('feedback-sent-id')).not.toBeEmpty()
  await dialog.getByRole('button', { name: 'Done' }).click()
  await expect(dialog).toBeHidden()
})
