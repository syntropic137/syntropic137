/**
 * Shared plumbing for surfaces that float above the page: Popover, Dropdown
 * Menu, Tooltip, and the Command list.
 *
 * - One stack of open layers per document. Escape closes only the topmost,
 *   so a popover inside a dialog closes before the dialog does (the keydown
 *   is cancelled, which also stops the native <dialog> "cancel").
 * - Pointer-down outside a layer's own elements closes it ("light dismiss").
 * - `positionFloating` keeps a fixed-position surface attached to its anchor
 *   through scroll and resize.
 */
import { placeFloating, type Align, type Side } from './floating'

export interface Layer {
  /** Elements that count as inside (the surface and its trigger). */
  contains: (target: Node) => boolean
  onEscape: () => void
  onOutside: () => void
}

const stack: Layer[] = []
let listening = false

function onKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape' || stack.length === 0) return
  e.preventDefault()
  e.stopPropagation()
  stack[stack.length - 1]?.onEscape()
}

function onPointerdown(e: PointerEvent) {
  const t = e.target as Node | null
  if (!t) return
  // Walk from the top: a click inside an upper layer leaves lower ones open.
  for (let i = stack.length - 1; i >= 0; i--) {
    const layer = stack[i]!
    if (layer.contains(t)) return
    layer.onOutside()
  }
}

/** Register an open layer; returns the function that removes it. */
export function pushLayer(layer: Layer): () => void {
  stack.push(layer)
  if (!listening && typeof document !== 'undefined') {
    document.addEventListener('keydown', onKeydown, true)
    document.addEventListener('pointerdown', onPointerdown, true)
    listening = true
  }
  return () => {
    const i = stack.indexOf(layer)
    if (i >= 0) stack.splice(i, 1)
    if (stack.length === 0 && listening) {
      document.removeEventListener('keydown', onKeydown, true)
      document.removeEventListener('pointerdown', onPointerdown, true)
      listening = false
    }
  }
}

export interface PositionOptions {
  side?: Side
  align?: Align
  offset?: number
  /** Match the surface's min-width to the anchor's width. */
  matchWidth?: boolean
}

/**
 * Position `surface` (position: fixed) next to `anchor` and keep it there.
 * Sets `data-side` to the side actually used, and `--sky-available` to the
 * room on that side for max-height. Returns a cleanup function.
 */
export function positionFloating(anchor: HTMLElement, surface: HTMLElement, opts: PositionOptions = {}): () => void {
  let frame = 0
  const update = () => {
    frame = 0
    const a = anchor.getBoundingClientRect()
    if (opts.matchWidth) surface.style.minWidth = `${Math.round(a.width)}px`
    const f = surface.getBoundingClientRect()
    const p = placeFloating({
      anchor: { x: a.left, y: a.top, width: a.width, height: a.height },
      floating: { width: f.width, height: f.height },
      viewport: { width: document.documentElement.clientWidth || innerWidth, height: innerHeight },
      side: opts.side ?? 'bottom',
      align: opts.align ?? 'start',
      offset: opts.offset ?? 8,
    })
    surface.style.left = `${p.x}px`
    surface.style.top = `${p.y}px`
    surface.style.setProperty('--sky-available', `${Math.floor(p.available)}px`)
    surface.dataset.side = p.side
  }
  const schedule = () => {
    if (!frame) frame = requestAnimationFrame(update)
  }
  update()
  addEventListener('scroll', schedule, true)
  addEventListener('resize', schedule)
  const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(schedule) : null
  ro?.observe(surface)
  ro?.observe(anchor)
  return () => {
    if (frame) cancelAnimationFrame(frame)
    removeEventListener('scroll', schedule, true)
    removeEventListener('resize', schedule)
    ro?.disconnect()
  }
}

/**
 * `popover="manual"` when the browser has the Popover API, else undefined.
 * Without the API the surface still works as a fixed-position layer; setting
 * the attribute anyway could hide it (a UA rule without showPopover()).
 */
export const popoverAttr: 'manual' | undefined =
  typeof HTMLElement !== 'undefined' && typeof HTMLElement.prototype.showPopover === 'function' ? 'manual' : undefined

/** Put a `popover="manual"` element in the top layer when the browser supports it. */
export function showInTopLayer(el: HTMLElement): void {
  if (typeof el.showPopover === 'function' && el.hasAttribute('popover')) {
    try {
      if (!el.matches(':popover-open')) el.showPopover()
    } catch {
      // Already open or detached: the fixed-position fallback still works.
    }
  }
}

export function hideFromTopLayer(el: HTMLElement): void {
  if (typeof el.hidePopover === 'function' && el.hasAttribute('popover')) {
    try {
      if (el.matches(':popover-open')) el.hidePopover()
    } catch {
      // Not open.
    }
  }
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function focusables(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.hasAttribute('inert') && !el.closest('[inert]'))
}

/** Count of open modal surfaces; the page stops scrolling while it is above zero. */
let scrollLocks = 0
let savedOverflow = ''
export function lockScroll(): () => void {
  if (typeof document === 'undefined') return () => {}
  if (scrollLocks++ === 0) {
    savedOverflow = document.documentElement.style.overflow
    document.documentElement.style.overflow = 'hidden'
  }
  let released = false
  return () => {
    if (released) return
    released = true
    if (--scrollLocks === 0) document.documentElement.style.overflow = savedOverflow
  }
}
