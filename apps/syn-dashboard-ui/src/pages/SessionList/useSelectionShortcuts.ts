/**
 * Wires Cmd/Ctrl+A (select all) and Esc (clear) to a row-selection hook.
 *
 * Skips Cmd+A when the user is typing in an input/textarea/contenteditable.
 */

import { useEffect } from 'react'

interface SelectionShortcutHandlers {
  selectAll: () => void
  clear: () => void
  hasSelection: boolean
}

function isTypingInField(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA'
}

export function useSelectionShortcuts({
  selectAll,
  clear,
  hasSelection,
}: SelectionShortcutHandlers): void {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && hasSelection) {
        clear()
        return
      }
      const isCmdA = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'a'
      if (isCmdA && !isTypingInField(e.target)) {
        e.preventDefault()
        selectAll()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectAll, clear, hasSelection])
}
