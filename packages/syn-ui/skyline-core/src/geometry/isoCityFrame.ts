/**
 * Framing for the IsoCity window (owner, Oct 10).
 *
 * isoCityCentred(): the boards put the first Monday at a fixed `ox`, which
 * leaves the window off-centre. This moves `ox` so the window's footprint,
 * first column's left edge to last column's right edge across all seven
 * rows, has equal margins in the free width: the whole view box on a
 * phone, the part left of the docked readout on the desktop board (where
 * the leader line turns, `leadX`), so today's blocks never slide under the
 * readout.
 *
 * isoCityEdgeMask(): a gradient along the week axis whose iso-lines run
 * along the weekday axis, so a whole week column fades together whatever
 * its depth. Opaque over the window, fading to nothing over the buffer
 * weeks either side: blocks gliding in and out fade instead of popping.
 */
import type { IsoCityDims } from './isoCityFloor'

/** The window's horizontal extent in view box units: [left, right]. */
export function isoCityExtent(dims: IsoCityDims, window = dims.win): [number, number] {
  const left = dims.ox + Math.min(0, (6 + dims.f) * dims.bx)
  const right = dims.ox + (window - 1 + dims.f) * dims.ax + Math.max(0, (6 + dims.f) * dims.bx)
  return [left, right]
}

/** The width the window is centred in: left of the dock when there is one. */
export function isoCityFreeWidth(dims: IsoCityDims): number {
  return dims.leadX > 0 ? dims.leadX : dims.vw
}

/** `dims` with `ox` moved so the window sits in the middle of the free width. */
export function isoCityCentred(dims: IsoCityDims, window = dims.win): IsoCityDims {
  const [left, right] = isoCityExtent(dims, window)
  const ox = dims.ox + (isoCityFreeWidth(dims) - right - left) / 2
  return { ...dims, ox: Math.round(ox * 100) / 100 }
}

export interface IsoEdgeMask {
  x1: number
  y1: number
  x2: number
  y2: number
  /** Gradient stops, offset 0..1 along the line, opacity 0..1. */
  stops: { offset: number; opacity: number }[]
}

const r2 = (v: number) => Math.round(v * 100) / 100

/** The edge fade for a window of `window` weeks with `fade` weeks of fade either side. */
export function isoCityEdgeMask(dims: IsoCityDims, window = dims.win, fade = 1): IsoEdgeMask {
  // Normal to the weekday axis: every depth of one column projects to the same offset.
  const nl = Math.hypot(dims.bx, dims.by)
  const n: [number, number] = [-dims.by / nl, dims.bx / nl]
  const step = dims.ax * n[0] + dims.ay * n[1]
  const from = -fade - 0.5
  const to = window + dims.f + fade
  const len = (to - from) * step
  const x1 = dims.ox + from * dims.ax
  const y1 = dims.oy + from * dims.ay
  const at = (c: number) => r2((c - from) / (to - from))
  return {
    x1: r2(x1),
    y1: r2(y1),
    x2: r2(x1 + n[0] * len),
    y2: r2(y1 + n[1] * len),
    stops: [
      { offset: at(-fade), opacity: 0 },
      { offset: at(0), opacity: 1 },
      { offset: at(window - 1 + dims.f), opacity: 1 },
      { offset: at(window - 1 + dims.f + fade), opacity: 0 },
    ],
  }
}

/** Fewest and most weeks the desktop board shows when it fits its column. */
export const ISO_FIT_WEEKS = { min: 8, max: 30 } as const

/**
 * The desktop board fitted to its own column (owner, Oct 10: the readout
 * sits beside the board, never over it). One view box unit is one CSS pixel
 * of column, so blocks keep their size and the board its height; the window
 * gets as many weeks as fit with at least one cell (`ax`) of gutter either
 * side, and is centred in the column. The leader line ends at the column's
 * right edge, where the readout starts. `columnPx` 0 (not measured yet)
 * keeps the board as drawn.
 */
export function isoCityFit(board: IsoCityDims, columnPx: number, window?: number): IsoCityDims {
  if (!(columnPx > 0)) return isoCityCentred(board, window ?? board.win)
  const depth = (6 + board.f) * board.bx
  const fits = Math.floor((columnPx - 2 * board.ax - depth) / board.ax + 1 - board.f)
  const win = window ?? Math.min(ISO_FIT_WEEKS.max, Math.max(ISO_FIT_WEEKS.min, fits))
  const [left, right] = isoCityExtent(board, win)
  const vw = Math.max(Math.round(columnPx), Math.ceil(right - left + 2 * board.ax))
  return isoCityCentred({ ...board, win, vw, leadX: board.leadX > 0 ? vw : 0 }, win)
}
