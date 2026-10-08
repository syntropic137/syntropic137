/**
 * Placement maths for floating surfaces (Popover, Dropdown Menu, Tooltip).
 * Pure: rectangles in, coordinates out, so it runs under Vitest in Node.
 *
 * The surface goes on the preferred side of its anchor, flips to the
 * opposite side when it does not fit there and fits better on the other,
 * and is clamped into the viewport on the cross axis. Coordinates are for
 * `position: fixed`.
 *
 * TODO(#624): move to @syn137/skyline-core/geometry once the patterns wave
 * settles that module's index (kept here to respect file ownership).
 */
export type Side = 'top' | 'right' | 'bottom' | 'left'
export type Align = 'start' | 'center' | 'end'

export interface Box {
  x: number
  y: number
  width: number
  height: number
}

export interface PlaceOptions {
  anchor: Box
  floating: { width: number; height: number }
  viewport: { width: number; height: number }
  side?: Side
  align?: Align
  /** Gap between anchor and surface. */
  offset?: number
  /** Minimum distance kept from the viewport edge. */
  padding?: number
}

export interface Placement {
  x: number
  y: number
  side: Side
  /** Room available on the chosen side, for max-height / max-width. */
  available: number
}

const OPPOSITE: Record<Side, Side> = { top: 'bottom', bottom: 'top', left: 'right', right: 'left' }

function room(side: Side, a: Box, vw: number, vh: number, offset: number, padding: number): number {
  switch (side) {
    case 'top':
      return a.y - offset - padding
    case 'bottom':
      return vh - (a.y + a.height) - offset - padding
    case 'left':
      return a.x - offset - padding
    case 'right':
      return vw - (a.x + a.width) - offset - padding
  }
}

export function placeFloating(opts: PlaceOptions): Placement {
  const { anchor: a, floating: f, viewport: v } = opts
  const offset = opts.offset ?? 8
  const padding = opts.padding ?? 8
  const align = opts.align ?? 'center'
  let side = opts.side ?? 'bottom'

  const vertical = (s: Side) => s === 'top' || s === 'bottom'
  const need = (s: Side) => (vertical(s) ? f.height : f.width)
  const here = room(side, a, v.width, v.height, offset, padding)
  if (here < need(side)) {
    const other = OPPOSITE[side]
    const there = room(other, a, v.width, v.height, offset, padding)
    if (there > here) side = other
  }

  let x: number
  let y: number
  if (vertical(side)) {
    y = side === 'bottom' ? a.y + a.height + offset : a.y - offset - f.height
    x = align === 'start' ? a.x : align === 'end' ? a.x + a.width - f.width : a.x + (a.width - f.width) / 2
    x = clamp(x, padding, v.width - padding - f.width)
  } else {
    x = side === 'right' ? a.x + a.width + offset : a.x - offset - f.width
    y = align === 'start' ? a.y : align === 'end' ? a.y + a.height - f.height : a.y + (a.height - f.height) / 2
    y = clamp(y, padding, v.height - padding - f.height)
  }
  return { x: Math.round(x), y: Math.round(y), side, available: Math.max(0, room(side, a, v.width, v.height, offset, padding)) }
}

/** Clamp into [min, max]; when the range is inverted (surface wider than the viewport) pin to min. */
function clamp(n: number, min: number, max: number): number {
  if (max < min) return min
  return Math.min(max, Math.max(min, n))
}
