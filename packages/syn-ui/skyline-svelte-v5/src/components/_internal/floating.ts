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
  const roomFor = (s: Side) => room(s, a, v.width, v.height, offset, padding)
  const side = chooseSide(opts.side ?? 'bottom', f, roomFor)
  const { x, y } = isVertical(side)
    ? { y: mainAxisStart(side, a.y, a.height, f.height, offset), x: crossAxisStart(a.x, a.width, f.width, v.width, align, padding) }
    : { x: mainAxisStart(side, a.x, a.width, f.width, offset), y: crossAxisStart(a.y, a.height, f.height, v.height, align, padding) }
  return { x: Math.round(x), y: Math.round(y), side, available: Math.max(0, roomFor(side)) }
}

function isVertical(s: Side): boolean {
  return s === 'top' || s === 'bottom'
}

/** Keep the preferred side unless the surface does not fit there and the opposite side has more room. */
function chooseSide(preferred: Side, f: { width: number; height: number }, roomFor: (s: Side) => number): Side {
  const here = roomFor(preferred)
  const need = isVertical(preferred) ? f.height : f.width
  if (here >= need) return preferred
  const other = OPPOSITE[preferred]
  return roomFor(other) > here ? other : preferred
}

/** Main-axis coordinate: after the anchor for bottom/right, before it for top/left. */
function mainAxisStart(side: Side, start: number, length: number, size: number, offset: number): number {
  return side === 'bottom' || side === 'right' ? start + length + offset : start - offset - size
}

/** Cross-axis coordinate aligned to the anchor, then clamped into the viewport. */
function crossAxisStart(start: number, length: number, size: number, viewport: number, align: Align, padding: number): number {
  const aligned = align === 'start' ? start : align === 'end' ? start + length - size : start + (length - size) / 2
  return clamp(aligned, padding, viewport - padding - size)
}

/** Clamp into [min, max]; when the range is inverted (surface wider than the viewport) pin to min. */
function clamp(n: number, min: number, max: number): number {
  if (max < min) return min
  return Math.min(max, Math.max(min, n))
}
