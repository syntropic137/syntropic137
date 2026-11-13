// @vitest-environment jsdom
// The palette's copy commands over plain http (#742): no Clipboard API, so
// "Copy page for an agent" must reach the clipboard through writeClipboard's
// execCommand fallback.
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { startClient } from '../lib/client'
import { overlays } from './overlays.svelte'

const settle = async () => {
  for (let i = 0; i < 10; i++) {
    await new Promise((r) => setTimeout(r, 10))
    flushSync()
  }
}

const copied: string[] = []

// jsdom has no modal dialogs; the palette opens in one. The stubs mark each
// modal with the order it opened in, so the double below can tell a modal
// (everything else inert) from a non-modal dialog and find the top one.
const MODAL = 'data-test-modal'
let opened = 0
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
  this.setAttribute('open', '')
  this.setAttribute(MODAL, String(++opened))
}
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
  this.removeAttribute('open')
  this.removeAttribute(MODAL)
}

function topModal(): HTMLDialogElement | undefined {
  const modals = [...document.querySelectorAll<HTMLDialogElement>(`dialog[open][${MODAL}]`)]
  return modals.sort((a, b) => Number(a.getAttribute(MODAL)) - Number(b.getAttribute(MODAL))).at(-1)
}

beforeEach(() => {
  copied.length = 0
  startClient(true)
  // A page that is not a secure context: no navigator.clipboard, only execCommand('copy').
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
  Object.defineProperty(document, 'execCommand', {
    configurable: true,
    value: (command: string) => {
      const area = document.querySelector<HTMLTextAreaElement>('textarea[readonly]')
      if (command !== 'copy' || !area) return false
      // Chromium returns true even when nothing is selected, or when the
      // textarea is inert outside the top modal (the open palette); it just
      // copies nothing (#742, #2263). So record only the selected text of a
      // live textarea.
      const top = topModal()
      if (!top || top.contains(area)) copied.push(area.value.slice(area.selectionStart, area.selectionEnd))
      return true
    },
  })
})
afterEach(() => {
  startClient(false)
  delete (navigator as { clipboard?: Clipboard }).clipboard
  delete (document as { execCommand?: Document['execCommand'] }).execCommand
  overlays.palette = false
})

describe('Command palette copy', () => {
  it('copies the page for an agent without a secure context', async () => {
    const { default: CommandPalette } = await import('./CommandPalette.svelte')
    const target = document.createElement('div')
    document.body.append(target)
    overlays.openPalette()
    const app = mount(CommandPalette, { target })
    try {
      await settle()
      const item = [...document.querySelectorAll<HTMLElement>('[role="option"]')].find((o) => o.textContent?.includes('Copy page for an agent'))
      expect(item, 'the palette lists Copy page for an agent').toBeTruthy()
      item!.click()
      await settle()
      expect(copied).toHaveLength(1)
      expect(copied[0]).toContain(location.href)
    } finally {
      unmount(app)
      target.remove()
    }
  })
})
