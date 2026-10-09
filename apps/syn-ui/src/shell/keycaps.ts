/**
 * Keycap labels for KEYMAP tokens, rendered by the Keycaps pattern. Elsewhere
 * `Ctrl Shift F`. On Apple platforms `Mod+k` is `⌘ K`, but a Mod+Shift chord
 * is shown as `⌃ ⇧ F`: those are the React widget's Ctrl chords (Mod accepts
 * Ctrl), and Cmd+Shift+T / F are the browser's reopen-tab and fullscreen.
 */
import { KEYMAP } from '@syn137/skyline-core/state'
import { APPLE } from './overlays.svelte'

const NAMED: Record<string, string> = { ArrowDown: '↓', ArrowUp: '↑', Escape: 'Esc', Backspace: '⌫', Enter: '↵' }

export function tokenCaps(token: string, apple: boolean = APPLE): string[] {
  const parts = token.split('+')
  const key = parts.pop() ?? ''
  const shifted = parts.includes('Shift')
  const caps = parts.map((m) => {
    if (m === 'Mod') return apple ? (shifted ? '⌃' : '⌘') : 'Ctrl'
    if (m === 'Shift') return apple ? '⇧' : 'Shift'
    return m
  })
  caps.push(NAMED[key] ?? (key.length === 1 ? key.toLocaleUpperCase() : key))
  return caps
}

/** Caps for the first chord of a KEYMAP binding, or none when it is not bound. */
export function bindingCaps(id: string, which = 0, apple: boolean = APPLE): string[] {
  const seq = KEYMAP.find((b) => b.id === id)?.keys[which]
  return seq?.length === 1 ? tokenCaps(seq[0]!, apple) : []
}
