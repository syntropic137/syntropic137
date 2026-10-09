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
import { openFeedback, showFeedbackRecent } from './feedback.svelte'
import { overlays, requestPalette } from './overlays.svelte'

const ROW = '[data-sky-row]'
const ACTIVE = 'data-sky-active'
// A closed <dialog role="dialog"> stays in the DOM, so only open ones count.
const MODAL = 'dialog[open], [role="dialog"]:not(dialog), [role="alertdialog"]:not(dialog), [role="menu"]'
const TEXT_INPUTS = new Set(['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file', 'image'])

const SECTION_HREF = Object.fromEntries(SECTIONS.map((s) => [s.key, s.href])) as Record<KeymapSection, string>

export function isTyping(el: Element | null): boolean {
  if (!(el instanceof HTMLElement)) return false
  if (el.isContentEditable) return true
  if (el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) return true
  return el instanceof HTMLInputElement && !TEXT_INPUTS.has(el.type)
}

/** Rendered and visible: a screen may keep a second layout's rows in the DOM, hidden by CSS. */
const shown = (el: Element) => el.getClientRects().length > 0

const rows = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>(`#sky-main ${ROW}`)].filter(shown)

const modalOpen = () => [...document.querySelectorAll(MODAL)].some(shown)

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

/** Only step back within the app: never off to the page (or blank tab) before it. */
function canGoBack(): boolean {
  const nav = (globalThis as { navigation?: { canGoBack: boolean } }).navigation
  return nav ? nav.canGoBack : history.length > 1
}

function back(): boolean {
  const row = activeRow()
  if (row) {
    row.removeAttribute(ACTIVE)
    return true
  }
  if (!canGoBack()) return false
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

type Handlers = { [T in KeyAction['type']]: (action: Extract<KeyAction, { type: T }>, key: string) => boolean }

/** One handler per action; each returns false when it did not apply here, so the key keeps its default. */
const HANDLERS: Handlers = {
  palette: () => (requestPalette(), true),
  help: () => (overlays.openShortcuts(), true),
  goto: (a) => (router.navigate(href(SECTION_HREF[a.section])), true),
  search: () => focusSearch(),
  // Arrows only drive rows when no control has focus; j and k always do.
  row: (a, key) => (key.startsWith('Arrow') && !focusIsFree() ? false : moveRow(a.move)),
  open: () => focusIsFree() && openRow(),
  back: () => back(),
  // False while the feedback feature is off, so the key keeps its default.
  feedback: (a) => (a.mode === 'recent' ? showFeedbackRecent() : openFeedback(a.mode)),
}

function perform<A extends KeyAction>(action: A, key: string): boolean {
  return (HANDLERS[action.type] as (a: A, key: string) => boolean)(action, key)
}

/** Install the handler on window; returns the remover. */
export function startKeyboard(): () => void {
  let state: KeymapState = KEYMAP_IDLE
  const onKey = (e: KeyboardEvent) => {
    if (e.defaultPrevented || e.isComposing) return
    const r = keymapStep(state, {
      key: e.key,
      mod: e.metaKey || e.ctrlKey,
      shift: e.shiftKey,
      alt: e.altKey,
      typing: isTyping(e.target instanceof Element ? e.target : document.activeElement),
      modal: modalOpen(),
      at: e.timeStamp,
    })
    state = r.state
    if (r.action ? perform(r.action, e.key) : r.handled) e.preventDefault()
  }
  addEventListener('keydown', onKey)
  // Lets tests (and anything else) know the lazily loaded handler is live.
  document.documentElement.dataset.skyKeys = 'ready'
  return () => {
    removeEventListener('keydown', onKey)
    delete document.documentElement.dataset.skyKeys
  }
}
