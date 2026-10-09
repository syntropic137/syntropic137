/**
 * Feedback bubble (#1385): in fixtures mode the API turns `ui_feedback` on, so
 * the bubble shows bottom right. One box (the comment) is the whole required
 * input; type, priority, element and screenshots sit under Details. Covers
 * the shortcut, Cmd/Ctrl+Enter, the auto-closing Sent line, the hotkeys in
 * Details, element picking, an uploaded stub PNG (the html2canvas capture is
 * exercised live, not here) and the Recent detail view.
 * Skyline only and fixtures only (never file real feedback from a test).
 */
import { isFixtures, isSkyline } from './support/env'
import { expect, open, test } from './support/test'

test.skip(!isSkyline || !isFixtures, 'Skyline feedback bubble, fixtures mode only')

/** A valid 1x1 PNG: the fixture checks the declared type, the API checks the magic bytes. */
const PNG_1X1 = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64')

test('open, type, Cmd+Enter, Sent, closes itself', async ({ page }) => {
  await open(page, '/executions')
  await page.getByRole('button', { name: 'Send feedback' }).click()
  await page.getByRole('menuitem', { name: /Quick note/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Send feedback' })
  const box = dialog.getByRole('textbox', { name: 'Feedback' })
  await expect(box).toBeFocused()
  await expect(box).toHaveAttribute('placeholder', "What's on your mind?")

  // Empty sends nothing and says so.
  await page.keyboard.press('ControlOrMeta+Enter')
  await expect(dialog.getByText('Write something first.')).toBeVisible()

  await box.fill('The run list jumps when a row finishes')
  // Type and priority stay visible, defaulting to Other / Medium; the page chip is visible too.
  await expect(dialog.getByTestId('feedback-type-other')).toHaveAttribute('aria-checked', 'true')
  await expect(dialog.getByTestId('feedback-priority-medium')).toHaveAttribute('aria-checked', 'true')
  await expect(dialog.getByTestId('feedback-attached')).toContainText('/executions')
  await expect(dialog.getByRole('button', { name: /Take screenshot/ })).toBeVisible()
  await expect(dialog.getByRole('button', { name: /Record voice/ })).toBeVisible()
  await page.keyboard.press('ControlOrMeta+Enter')
  await expect(dialog.getByRole('status')).toContainText('Sent')
  await expect(dialog.getByTestId('feedback-sent-id')).not.toBeEmpty()
  await expect(dialog).toBeHidden({ timeout: 3000 })
})

test('Esc closes the box', async ({ page }) => {
  await open(page, '/executions')
  // `f` only works once the bubble knows the feature is on.
  await expect(page.getByRole('button', { name: 'Send feedback' })).toBeVisible()
  await page.locator('#sky-main').focus()
  await page.keyboard.press('f')
  const dialog = page.getByRole('dialog', { name: 'Send feedback' })
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})

test('details: hotkeys pick type and priority, pick an element, upload, send', async ({ page }) => {
  await open(page, '/executions')
  // `f` only works once the bubble knows the feature is on.
  await expect(page.getByRole('button', { name: 'Send feedback' })).toBeVisible()
  await page.locator('#sky-main').focus()
  await page.keyboard.press('f')
  const dialog = page.getByRole('dialog', { name: 'Send feedback' })
  await dialog.getByRole('textbox', { name: 'Feedback' }).fill('Heading spacing')

  await dialog.getByTestId('feedback-type-other').focus()
  await page.keyboard.press('u')
  await page.keyboard.press('3')
  await expect(dialog.getByTestId('feedback-type-ui_ux')).toHaveAttribute('aria-checked', 'true')
  await expect(dialog.getByTestId('feedback-priority-high')).toHaveAttribute('aria-checked', 'true')

  await page.keyboard.press('e')
  const picker = page.getByTestId('feedback-picker')
  await expect(picker).toBeVisible()
  const heading = page.locator('#sky-main h1').first()
  const hb = await heading.boundingBox()
  if (!hb) throw new Error('no heading to pick')
  await page.mouse.move(hb.x + 8, hb.y + hb.height / 2)
  await page.mouse.click(hb.x + 8, hb.y + hb.height / 2)
  await expect(picker).toBeHidden()
  await expect(dialog.getByTestId('feedback-element')).toContainText('h1')

  // Esc in the picker cancels and returns to the draft.
  await dialog.getByRole('button', { name: 'Re-pick' }).click()
  await expect(picker).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByTestId('feedback-element')).toContainText('h1')
  await expect(dialog.getByRole('textbox', { name: 'Feedback' })).toHaveValue('Heading spacing')

  await dialog.getByTestId('feedback-file').setInputFiles({ name: 'stub.png', mimeType: 'image/png', buffer: PNG_1X1 })
  await expect(dialog.getByRole('img', { name: 'Screenshot 1' })).toBeVisible()
  await dialog.getByRole('button', { name: 'Send', exact: true }).click()
  await expect(dialog.getByRole('status')).toContainText('with 1 attachment')
  await expect(dialog).toBeHidden({ timeout: 3000 })
})

test('recent feedback: open an item, read the full comment, resolve, back', async ({ page }) => {
  await open(page, '/executions')
  const bubble = page.getByRole('button', { name: 'Send feedback' })
  await bubble.click()
  await page.getByRole('menuitem', { name: /Quick note/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Send feedback' })
  await dialog.getByRole('textbox', { name: 'Feedback' }).fill('Detail summary\nLine one\nLine two')
  await page.keyboard.press('ControlOrMeta+Enter')
  await expect(dialog).toBeHidden({ timeout: 3000 })

  await bubble.click()
  await page.getByRole('menuitem', { name: /Recent feedback/ }).click()
  const list = page.getByRole('list', { name: 'Recent feedback' })
  const first = list.getByRole('button').first()
  await expect(first).toContainText('Detail summary')
  await expect(first).not.toContainText('Line one')
  await first.focus()
  await page.keyboard.press('Enter')

  const detail = page.getByTestId('feedback-detail')
  await expect(detail.getByTestId('feedback-detail-comment')).toHaveText('Detail summary\nLine one\nLine two')
  await expect(detail).toContainText('/executions')
  await detail.getByRole('button', { name: 'Mark resolved' }).click()
  await expect(detail.getByRole('button', { name: 'Reopen' })).toBeVisible()
  await expect(detail).toContainText('Resolved')

  await page.keyboard.press('Escape')
  await expect(detail).toBeHidden()
  await expect(list.getByRole('button').first()).toBeFocused()
})

/** A fake microphone: getUserMedia resolves (or is denied) and MediaRecorder emits one webm chunk. */
async function fakeMic(page: import('@playwright/test').Page, deny = false) {
  await page.addInitScript((denied: boolean) => {
    const md = navigator.mediaDevices ?? ({} as MediaDevices)
    Object.defineProperty(navigator, 'mediaDevices', { value: md, configurable: true })
    md.getUserMedia = async () => {
      if (denied) throw new DOMException('denied', 'NotAllowedError')
      return { getTracks: () => [{ stop() {} }] } as unknown as MediaStream
    }
    class FakeRecorder {
      static isTypeSupported(t: string) {
        return t.startsWith('audio/webm')
      }
      state: 'inactive' | 'recording' = 'inactive'
      mimeType = 'audio/webm;codecs=opus'
      ondataavailable: ((e: { data: Blob }) => void) | null = null
      onstop: (() => void) | null = null
      onerror: (() => void) | null = null
      start() {
        this.state = 'recording'
      }
      stop() {
        this.state = 'inactive'
        this.ondataavailable?.({ data: new Blob([new Uint8Array([0x1a, 0x45, 0xdf, 0xa3, 0, 0, 0, 0])], { type: this.mimeType }) })
        this.onstop?.()
      }
    }
    Object.defineProperty(window, 'MediaRecorder', { value: FakeRecorder, configurable: true })
  }, deny)
}

test('voice note: record, stop, play back, send, hear it in the detail', async ({ page }) => {
  await fakeMic(page)
  await open(page, '/executions')
  // `f` only works once the bubble knows the feature is on.
  await expect(page.getByRole('button', { name: 'Send feedback' })).toBeVisible()
  await page.locator('#sky-main').focus()
  await page.keyboard.press('f')
  const dialog = page.getByRole('dialog', { name: 'Send feedback' })
  await dialog.getByRole('textbox', { name: 'Feedback' }).fill('Voice summary')
  await dialog.getByRole('button', { name: /Record voice/ }).click()
  await expect(dialog.getByText(/Recording 0:0\d/)).toBeVisible()
  await dialog.getByRole('button', { name: 'Stop' }).click()
  await expect(dialog.getByLabel('Voice note', { exact: true })).toBeVisible()
  // Delete, record again, keep it.
  await dialog.getByRole('button', { name: 'Delete voice note' }).click()
  await dialog.getByRole('button', { name: /Record voice/ }).click()
  await dialog.getByRole('button', { name: 'Stop' }).click()
  // Focus fell to the page when Stop unmounted; Cmd/Ctrl+Enter still sends.
  await page.keyboard.press('ControlOrMeta+Enter')
  await expect(dialog.getByRole('status')).toContainText('with 1 attachment')
  await expect(dialog).toBeHidden({ timeout: 3000 })

  await page.getByRole('button', { name: 'Send feedback' }).click()
  await page.getByRole('menuitem', { name: /Recent feedback/ }).click()
  await page.getByRole('list', { name: 'Recent feedback' }).getByRole('button').first().click()
  await expect(page.getByTestId('feedback-detail-voice')).toBeVisible()
})

test('voice note: a denied microphone says so', async ({ page }) => {
  await fakeMic(page, true)
  await open(page, '/executions')
  // `f` only works once the bubble knows the feature is on.
  await expect(page.getByRole('button', { name: 'Send feedback' })).toBeVisible()
  await page.locator('#sky-main').focus()
  await page.keyboard.press('f')
  const dialog = page.getByRole('dialog', { name: 'Send feedback' })
  await dialog.getByRole('button', { name: /Record voice/ }).click()
  await expect(dialog.getByRole('alert')).toContainText('Microphone permission denied')
})
