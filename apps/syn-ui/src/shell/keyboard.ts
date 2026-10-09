/**
 * The app-wide keyboard handler. Every binding lives in skyline-core's
 * KEYMAP; this file only reads the DOM (is the user typing, is a modal
 * open, which list rows exist) and performs the action.
 *
 * List rows opt in with `data-sky-row` (any element holding the row's
 * primary link). The active row carries `data-sky-active`; app.css draws
 * the focus ring from tokens.
 */
import { KEYMAP_IDLE, keymapStep, moveIndex, type KeyAction, type KeymapSection, type KeymapState } from '@syn137/skyline-core/state'
import { href, router } from '../lib/router'
import { SECTIONS } from './nav'
import { overlays, requestPalette } from './overlays.svelte'

const ROW = '[data-sky-row]'
const ACTIVE = 'data-sky-active'
const MODAL = 'dialog[open], [role="dialog"], [role="alertdialog"], [role="menu"]'
const TEXT_INPUTS = new Set(['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file', 'image'])

const SECTION_HREF = Object.fromEntries(SECTIONS.map((s) => [s.key, s.href])) as Record<KeymapSection, string>

export function isTyping(el: Element | null): boolean {
  if (!(el instanceof HTMLElement)) return false
  if (el.isContentEditable) return true
  if (el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) return true
  return el instanceof HTMLInputElement && !TEXT_INPUTS.has(el.type)
}

const rows = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>(`#sky-main ${ROW}`)]

/** Focus is on the page itself or a list row, not on a control that owns these keys. */
function focusIsFree(): boolean {
  const el = document.activeElement
  return !el || el === document.body || el.id === 'sky-main' || !!el.closest(ROW)
}

function moveRow(move: 'next' | 'prev'): boolean {
  const list = rows()
  if (list.length === 0) return false
  const current = list.findIndex((r) => r.hasAttribute(ACTIVE))
  const start = current < 0 ? (move === 'next' ? -1 : list.length) : current
  const next = moveIndex(start, move, list.map(() => false), false)
  if (next < 0) return false
  list[current]?.removeAttribute(ACTIVE)
  const row = list[next]!
  row.setAttribute(ACTIVE, '')
  row.scrollIntoView({ block: 'nearest' })
  return true
}

function activeRow(): HTMLElement | undefined {
  return rows().find((r) => r.hasAttribute(ACTIVE))
}

function openRow(): boolean {
  const row = activeRow()
  const link = row?.matches('a[href]') ? (row as HTMLAnchorElement) : row?.querySelector<HTMLAnchorElement>('a[href]')
  if (!link) return false
  link.click()
  return true
}

function back(): boolean {
  const row = activeRow()
  if (row) {
    row.removeAttribute(ACTIVE)
    return true
  }
  if (history.length <= 1) return false
  history.back()
  return true
}

function focusSearch(): boolean {
  const input = document.querySelector<HTMLInputElement>('#sky-main input[type="search"]')
  if (!input) return false
  input.focus()
  input.select()
  return true
}

/** Perform an action; false when it did not apply here, so the key keeps its default. */
function perform(action: KeyAction, key: string): boolean {
  switch (action.type) {
    case 'palette':
      requestPalette()
      return true
    case 'help':
      overlays.openShortcuts()
      return true
    case 'goto':
      router.navigate(href(SECTION_HREF[action.section]))
      return true
    case 'search':
      return focusSearch()
    case 'row':
      // Arrows only drive rows when no control has focus; j and k always do.
      return key.startsWith('Arrow') && !focusIsFree() ? false : moveRow(action.move)
    case 'open':
      return focusIsFree() && openRow()
    case 'back':
      return back()
  }
}

/** Install the handler on window; returns the remover. */
export function startKeyboard(): () => void {
  let state: KeymapState = KEYMAP_IDLE
  const onKey = (e: KeyboardEvent) => {
    if (e.defaultPrevented || e.isComposing) return
    const r = keymapStep(state, {
      key: e.key,
      mod: e.metaKey || e.ctrlKey,
      alt: e.altKey,
      typing: isTyping(e.target instanceof Element ? e.target : document.activeElement),
      modal: !!document.querySelector(MODAL),
      at: e.timeStamp,
    })
    state = r.state
    if (r.action ? perform(r.action, e.key) : r.handled) e.preventDefault()
  }
  addEventListener('keydown', onKey)
  return () => removeEventListener('keydown', onKey)
}
