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
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.inset = '0 auto auto 0'
  area.style.opacity = '0'
  document.body.append(area)
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
  }
}
