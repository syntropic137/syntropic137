/**
 * Trend chart maths (Eval and Workflows boards): time axis, nice axis
 * maxima, line paths, end-label spreading and a least-squares fit. Every
 * position is a percentage of the plot box, so the SVG and the HTML dots
 * laid over it share one coordinate system.
 */

/** A point in plot percentages: x 0 (left) to 100, y 0 (bottom) to 100. */
export interface TrendPoint {
  x: number
  y: number
}

/** Horizontal padding (percent) so the first and last dots are not clipped. */
export const TREND_X_PAD = 2

/** x percent of time `t` in [t0, t1], padded by TREND_X_PAD on each side. A zero span centres. */
export function timeX(t: number, t0: number, t1: number, pad = TREND_X_PAD): number {
  const span = t1 - t0
  if (span <= 0) return 50
  const f = Math.min(1, Math.max(0, (t - t0) / span))
  return pad + f * (100 - 2 * pad)
}

/** The first step at or above `v`; above them all, the next multiple of the last step. */
export function niceCeil(v: number, steps: readonly number[]): number {
  for (const s of steps) if (v <= s) return s
  const last = steps[steps.length - 1]
  return last ? Math.ceil(v / last) * last : v
}

/** y percent of `v` on a 0..max axis, clamped to the box. */
export function valueY(v: number, max: number): number {
  if (max <= 0) return 0
  return Math.min(100, Math.max(0, (v / max) * 100))
}

/** Evenly spaced values from 0 to max: axisTicks(4, 4) -> [0, 1, 2, 3, 4]. */
export function axisTicks(max: number, intervals = 4): number[] {
  return Array.from({ length: intervals + 1 }, (_, k) => (max * k) / intervals)
}

const r1 = (n: number) => Math.round(n * 10) / 10

/**
 * SVG path through points in plot percentages, for a viewBox of w x h with
 * preserveAspectRatio="none". Points are drawn in the order given.
 */
export function linePath(points: readonly TrendPoint[], w: number, h: number): string {
  return points.map((p, i) => `${i ? 'L' : 'M'}${r1((p.x / 100) * w)} ${r1(h - (p.y / 100) * h)}`).join(' ')
}

export interface EndLabel {
  key: string
  /** Distance from the top of the box, percent. */
  top: number
}

/**
 * Line-end labels pushed apart so none is closer than `gap` percent to the
 * next, then shifted up as a block if the last one fell off the bottom.
 * Returned in top-to-bottom order.
 */
export function spreadEndLabels(labels: readonly EndLabel[], gap = 11): EndLabel[] {
  const out = labels.map((l) => ({ ...l })).sort((a, b) => a.top - b.top)
  for (let k = 1; k < out.length; k++) out[k]!.top = Math.max(out[k]!.top, out[k - 1]!.top + gap)
  const over = (out[out.length - 1]?.top ?? 0) - 100
  if (over > 0) for (const l of out) l.top -= over
  return out
}

/** Least-squares line through ys at x = 0..n-1: the fitted first and last values. */
export function linearFit(ys: readonly number[]): { start: number; end: number } {
  const n = ys.length
  if (n === 0) return { start: 0, end: 0 }
  const mean = ys.reduce((a, y) => a + y, 0) / n
  if (n === 1) return { start: mean, end: mean }
  const mx = (n - 1) / 2
  let sxy = 0
  let sxx = 0
  ys.forEach((y, x) => {
    sxy += (x - mx) * (y - mean)
    sxx += (x - mx) * (x - mx)
  })
  const slope = sxy / sxx
  return { start: mean - slope * mx, end: mean + slope * mx }
}

/**
 * Sparkline path for values drawn oldest to newest in a w x h viewBox,
 * scaled between their own min and max with `inset` px kept free at top and
 * bottom. Fewer than two values draw a flat baseline.
 */
export function sparkPath(values: readonly number[], w = 200, h = 40, inset = 4): string {
  if (values.length < 2) return `M0 ${h - 2} L${w} ${h - 2}`
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const span = hi - lo
  const pts = values.map((v, i) => ({ x: (i / (values.length - 1)) * 100, y: span === 0 ? 50 : ((v - lo) / span) * 100 }))
  const inner = h - 2 * inset
  return pts.map((p, i) => `${i ? 'L' : 'M'}${r1((p.x / 100) * w)} ${r1(inset + inner - (p.y / 100) * inner)}`).join(' ')
}
