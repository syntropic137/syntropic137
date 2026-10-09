/**
 * Feedback modal (#1385): in fixtures mode the API turns `ui_feedback` on, so
 * the desktop nav shows the button; the modal files an item and says so.
 * Skyline only (the React widget is a different control) and fixtures only
 * (never file real feedback from a test).
 */
import { isFixtures, isSkyline } from './support/env'
import { expect, open, test } from './support/test'

test.skip(!isSkyline || !isFixtures, 'Skyline feedback modal, fixtures mode only')

test('opens from the nav, submits, shows success, Esc closes', async ({ page }) => {
  await open(page, '/executions')
  const button = page.getByRole('button', { name: 'Send feedback' }).first()
  await button.click()

  const dialog = page.getByRole('dialog', { name: 'Send feedback' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('checkbox', { name: "Include this page's URL" })).toBeChecked()

  // Title is required: submitting empty says so and sends nothing.
  await dialog.getByRole('button', { name: 'Send feedback' }).click()
  await expect(dialog.getByText('Add a title.')).toBeVisible()

  await dialog.getByLabel('Type').selectOption('feature')
  await dialog.getByLabel('Title').fill('syn-ui feedback modal e2e')
  await dialog.getByLabel('Description').fill('Filed by feedback.spec.ts in fixtures mode.')
  await dialog.getByRole('button', { name: 'Send feedback' }).click()

  await expect(dialog.getByRole('status')).toContainText('Thanks, feedback sent.')
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(button).toBeFocused()
})
