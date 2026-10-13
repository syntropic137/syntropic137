/**
 * Outcome Ring (Main board, Outcomes card): the share of completed, failed
 * and cancelled runs as stroked arcs on one circle.
 *
 * Each arc is a dashed <circle> rotated -90deg: `dasharray` is the arc
 * length (less a small gap so neighbours stay apart) and the circumference;
 * `dashoffset` moves it to start where the previous arc ended.
 */
import { round2 } from './path'

export interface OutcomeRingDims {
  size: number
  radius: number
  stroke: number
  /** Gap left at the end of each arc, in px along the circle. */
  gap: number
}

export const OUTCOME_RING: OutcomeRingDims = { size: 120, radius: 46, stroke: 12, gap: 3 }

export interface RingArc<K extends string = string> {
  key: K
  value: number
  share: number
  dasharray: string
  dashoffset: number
}

export interface RingLayout<K extends string = string> {
  circumference: number
  total: number
  arcs: RingArc<K>[]
}

export function layoutRing<K extends string>(parts: readonly { key: K; value: number }[], dims: OutcomeRingDims = OUTCOME_RING): RingLayout<K> {
  // Rounded first, as the board does, so offsets match it to the hundredth.
  const circumference = round2(2 * Math.PI * dims.radius)
  const total = parts.reduce((s, p) => s + Math.max(0, p.value), 0)
  let at = 0
  const arcs: RingArc<K>[] = []
  if (total > 0) {
    for (const p of parts) {
      if (p.value <= 0) continue
      const len = (p.value / total) * circumference
      // A lone part closes the ring; otherwise leave the gap.
      const dash = parts.filter((q) => q.value > 0).length === 1 ? circumference : Math.max(0.5, len - dims.gap)
      arcs.push({ key: p.key, value: p.value, share: p.value / total, dasharray: `${round2(dash)} ${round2(circumference)}`, dashoffset: round2(-at) })
      at += len
    }
  }
  return { circumference: round2(circumference), total, arcs }
}

/** Whole percent of a part, rounded half up: 50 of 75 -> 67. */
export function percentOf(value: number, total: number): number {
  return total > 0 ? Math.round((value / total) * 100) : 0
}
