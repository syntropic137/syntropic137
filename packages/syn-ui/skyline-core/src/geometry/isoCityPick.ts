/**
 * Visible-surface picking for the IsoCity (codex review of #1856): which day
 * is under a point. Blocks overlap on screen (a nearer, taller block covers
 * part of the ones behind it), so a rectangle per block picks the wrong day.
 * This tests the painted faces themselves, in painter order, and the last
 * block painted under the point wins, exactly what the eye sees.
 */
import type { IsoCityBlock } from './isoCityFloor'
import type { Point } from './path'

/** Even-odd point in polygon; a point on an edge counts as inside. */
export function pointInPolygon(x: number, y: number, poly: readonly Point[]): boolean {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i]!
    const [xj, yj] = poly[j]!
    if (onSegment(x, y, xi, yi, xj, yj)) return true
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

function onSegment(x: number, y: number, x1: number, y1: number, x2: number, y2: number): boolean {
  const cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
  if (Math.abs(cross) > 1e-6) return false
  return x >= Math.min(x1, x2) && x <= Math.max(x1, x2) && y >= Math.min(y1, y2) && y <= Math.max(y1, y2)
}

/** True when the point falls on one of the block's painted faces. */
export function blockCovers(b: IsoCityBlock, x: number, y: number): boolean {
  return b.faces.some((f) => pointInPolygon(x, y, f))
}

/**
 * The block painted on top at view box point (x, y), or null for floor.
 * `blocks` in draw order (layout.blocks); edge weeks outside the window are
 * hidden at rest and never picked.
 */
export function pickIsoCityBlock(blocks: readonly IsoCityBlock[], x: number, y: number): IsoCityBlock | null {
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i]!
    if (b.inWindow && blockCovers(b, x, y)) return b
  }
  return null
}

/** Client point to view box units, given the box the chart is drawn in. */
export function toViewBox(clientX: number, clientY: number, box: { left: number; top: number; width: number; height: number }, vw: number, vh: number): Point | null {
  if (box.width <= 0 || box.height <= 0) return null
  return [((clientX - box.left) / box.width) * vw, ((clientY - box.top) / box.height) * vh]
}
