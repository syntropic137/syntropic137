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

// jsdom has no modal dialogs; the palette opens in one.
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
  this.setAttribute('open', '')
}
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
  this.removeAttribute('open')
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
      // The palette is an open modal dialog and everything outside it is inert:
      // Chromium returns true and copies nothing, so record nothing (#742).
      const modal = document.querySelector('dialog[open]')
      if (!modal || modal.contains(area)) copied.push(area.value)
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
