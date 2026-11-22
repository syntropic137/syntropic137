/**
 * Write text to the clipboard. Uses the async Clipboard API where it exists
 * (secure contexts) and falls back to execCommand('copy'), which still works on a
 * self-hosted dashboard served over plain HTTP on a LAN address.
 */
export async function writeClipboard(text: string): Promise<void> {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // Permission denied or not focused: try the legacy path.
    }
  }
  if (typeof document.execCommand !== 'function') throw new Error('Clipboard is not available')
  copyThroughTextarea(text)
}

/** The execCommand('copy') path: select a hidden textarea, copy, put focus and selection back. */
function copyThroughTextarea(text: string): void {
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.inset = '0 auto auto 0'
  area.style.opacity = '0'
  fallbackHost().append(area)
  const focused = document.activeElement
  const selection = document.getSelection()
  const previous = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null
  area.select()
  try {
    if (!document.execCommand('copy')) throw new Error('Copy was blocked by the browser')
  } finally {
    area.remove()
    if (previous && selection) {
      selection.removeAllRanges()
      selection.addRange(previous)
    }
    if (focused instanceof HTMLElement && focused.isConnected) focused.focus({ preventScroll: true })
  }
}

/**
 * Where the fallback textarea goes. While a native modal `<dialog>` is open,
 * everything outside it is inert and cannot be selected, and Chromium still
 * returns true from execCommand('copy') with the clipboard unchanged (#742).
 * So the textarea goes inside the modal that holds focus: a modal moves focus
 * into itself when opened, and every copy control in this app runs from inside
 * it, so that is the top-most one in practice. With focus outside every modal,
 * the last `:modal` in document order is a best guess only: the top layer
 * stacks modals by the order `showModal()` was called, which the DOM does not
 * record (#2263). With no modal open it goes into the body.
 */
function fallbackHost(): HTMLElement {
  const active = document.activeElement
  const owner = active instanceof Element ? active.closest('dialog[open]') : null
  if (owner instanceof HTMLElement) return owner
  try {
    const top = [...document.querySelectorAll<HTMLElement>('dialog:modal')].at(-1)
    if (top) return top
  } catch {
    // `:modal` is not supported by this engine: fall through to the body.
  }
  return document.body
}
