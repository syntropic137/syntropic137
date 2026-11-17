// @vitest-environment jsdom
// writeClipboard's execCommand fallback under native modal dialogs (#742,
// #2263): only the top modal is live, so that is where the copy has to happen.
import '../_test/setup'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { insecureClipboard, type InsecureClipboard } from '../_test/clipboard'
import { writeClipboard } from './clipboard'

let clipboard: InsecureClipboard
beforeEach(() => {
  clipboard = insecureClipboard()
})
afterEach(() => {
  clipboard.restore()
  document.body.replaceChildren()
})

function openModal(label: string): HTMLDialogElement {
  const dialog = document.createElement('dialog')
  dialog.setAttribute('aria-label', label)
  document.body.append(dialog)
  dialog.showModal()
  return dialog
}

describe('writeClipboard fallback', () => {
  it('copies inside the top modal when two are open and nothing has focus', async () => {
    openModal('Settings')
    openModal('Confirm')
    ;(document.activeElement as HTMLElement | null)?.blur()
    expect(document.activeElement).toBe(document.body)

    await writeClipboard('exec-7b2f')

    expect(clipboard.copied).toEqual(['exec-7b2f'])
  })

  it('copies inside the modal that holds focus', async () => {
    const dialog = openModal('Command palette')
    const input = document.createElement('input')
    dialog.append(input)
    input.focus()

    await writeClipboard('exec-7b2f')

    expect(clipboard.copied).toEqual(['exec-7b2f'])
    expect(document.activeElement).toBe(input)
  })

  it('puts focus back without scrolling to it', async () => {
    const button = document.createElement('button')
    document.body.append(button)
    button.focus()
    const focus = vi.spyOn(button, 'focus')

    await writeClipboard('exec-7b2f')

    expect(focus).toHaveBeenCalledWith({ preventScroll: true })
    expect(document.activeElement).toBe(button)
  })
})
