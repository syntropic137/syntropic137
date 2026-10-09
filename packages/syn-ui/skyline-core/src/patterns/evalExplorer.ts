/**
 * Eval explorer (Landing section 04; later a compact mode on the Evals
 * list): quality and cost per run over time for a few verifiers, ranked by
 * quality per dollar, with a one-line verdict on the picked one. Ported
 * from explorer() and EXPLORER_JS in design/reference/gen_landing3.py.
 *
 * Charts are drawn in a 1000-wide box stretched to the container
 * (preserveAspectRatio="none", non-scaling strokes): x is the run's day
 * across the span with a 2% inset each side, y the score (0..100) or the
 * cost (0..costMax).
 */
import { PASS_SCORE } from '../screens/evals/trend'
import { rankVerdict, rankVerifiers, type RankRow, type RankVerdict, type RankVerifierInput } from '../screens/evals/ranking'

export interface ExplorerVerifier {
  /** Model or workflow under test: "claude-sonnet-5-5". */
  name: string
  /** Series colour: a slot 1..4 (--sky-color-series-N) or a token name. Default: its position. */
  colour?: number | `--${string}`
  /** Judge score 0..100 per run, oldest first; null for a run not scored yet. */
  scores: readonly (number | null)[]
  /** USD per run, in the same order as `scores`. */
  costs: readonly number[]
  /** Day of each run on the x axis, 0 = the first day. Default: spread evenly over the span. */
  days?: readonly number[]
}

export interface EvalExplorerProps {
  verifiers: readonly ExplorerVerifier[]
  /** A run passes at this score (default 70); drawn as a dashed line. */
  passAt?: number
  /** Judge model named over the quality chart. */
  judge?: string
  /** Index (into `verifiers`) of the picked verifier. Default: the best quality per dollar. */
  selected?: number
  /** Days across the x axis (default: the last run's day). */
  span?: number
  /** Labels under the cost chart, spread evenly: ["Sep 8", ..., "Oct 7"]. */
  ticks?: readonly string[]
  /** Top of the cost axis in USD (default: 1.28 times the dearest run, rounded up to 10 cents). */
  costMax?: number
}

/** Chart boxes, in viewBox units: QH and CH in the board. */
export const EXPLORER_CHART = { width: 1000, quality: 230, cost: 120 } as const

/** Number of series colours (--sky-color-series-1..N). */
export const EXPLORER_SLOTS = 4

export interface ExplorerLine {
  index: number
  /** SVG path in the chart's viewBox; "" when the series has no points. */
  d: string
  /** Colour token, e.g. "--sky-color-series-2". */
  token: string
}

export interface ExplorerRow extends RankRow {
  token: string
}

export interface ExplorerModel {
  quality: ExplorerLine[]
  cost: ExplorerLine[]
  /** Horizontal grid lines (0, 25, 50, 75, 100 % of the height), as y values. */
  qualityGrid: number[]
  costGrid: number[]
  /** The pass line: y in the quality box, its share from the top (0..1) and the label "pass 70". */
  pass: { y: number; top: number; label: string }
  rows: ExplorerRow[]
  /** The index actually picked (the requested one, clamped, or the best). */
  selected: number
  verdict: RankVerdict | null
  /** "/100 · $0.52 a run · +29 pts". */
  readout: string
  costMax: number
  /** "Ranked by quality per dollar: 1 claude-sonnet-5-5, 87 ..." for the chart's accessible name. */
  summary: string
}

/** CSS custom property for a verifier's colour. */
export function explorerColour(colour: ExplorerVerifier['colour'], index: number): string {
  if (typeof colour === 'string') return colour
  const slot = typeof colour === 'number' && Number.isFinite(colour) ? Math.max(1, Math.round(colour)) : index + 1
  return `--sky-color-series-${((slot - 1) % EXPLORER_SLOTS) + 1}`
}

const r1 = (v: number) => Math.round(v * 10) / 10

/** x in the 1000 box for day `d` of `span`: the board's (2 + d / span * 96) * 10. */
export function explorerX(d: number, span: number): number {
  return r1((2 + (span > 0 ? d / span : 0) * 96) * 10)
}

function daysOf(v: ExplorerVerifier, span: number): number[] {
  const n = Math.max(v.scores.length, v.costs.length)
  return Array.from({ length: n }, (_, i) => v.days?.[i] ?? (n > 1 ? (i / (n - 1)) * span : 0))
}

function path(points: [number, number][]): string {
  return points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x} ${y}`).join(' ')
}

/** Everything the explorer draws, from plain verifier series. */
export function explorerModel(p: EvalExplorerProps): ExplorerModel {
  const { quality: QH, cost: CH } = EXPLORER_CHART
  const passAt = p.passAt ?? PASS_SCORE
  const lastDay = Math.max(0, ...p.verifiers.flatMap((v) => v.days ?? []))
  const longest = Math.max(0, ...p.verifiers.map((v) => Math.max(v.scores.length, v.costs.length) - 1))
  const span = p.span ?? (lastDay > 0 ? lastDay : Math.max(1, longest))
  const dearest = Math.max(0, ...p.verifiers.flatMap((v) => v.costs.filter((c) => Number.isFinite(c))))
  const costMax = p.costMax ?? (dearest > 0 ? Math.ceil(dearest * 1.28 * 10) / 10 : 1)

  const quality: ExplorerLine[] = []
  const cost: ExplorerLine[] = []
  p.verifiers.forEach((v, index) => {
    const token = explorerColour(v.colour, index)
    const days = daysOf(v, span)
    const q: [number, number][] = []
    const c: [number, number][] = []
    days.forEach((d, i) => {
      const s = v.scores[i]
      if (typeof s === 'number' && Number.isFinite(s)) q.push([explorerX(d, span), r1(QH - (Math.min(100, Math.max(0, s)) / 100) * QH)])
      const k = v.costs[i]
      if (typeof k === 'number' && Number.isFinite(k)) c.push([explorerX(d, span), r1(CH - (Math.min(costMax, Math.max(0, k)) / costMax) * CH)])
    })
    quality.push({ index, d: path(q), token })
    cost.push({ index, d: path(c), token })
  })

  const inputs: RankVerifierInput[] = p.verifiers.map((v) => ({
    name: v.name,
    runs: Array.from({ length: Math.max(v.scores.length, v.costs.length) }, (_, i) => ({ score: v.scores[i] ?? null, costUsd: v.costs[i] ?? 0 })),
  }))
  const ranking = rankVerifiers(inputs)
  const n = p.verifiers.length
  const requested = typeof p.selected === 'number' && Number.isInteger(p.selected) && p.selected >= 0 && p.selected < n ? p.selected : null
  const selected = requested ?? ranking.best ?? 0
  const stats = ranking.stats[selected]
  const verdict = stats ? rankVerdict(stats) : null
  const grid = (h: number) => [0, 0.25, 0.5, 0.75, 1].map((f) => h * f)
  const rows = ranking.rows.map((r): ExplorerRow => ({ ...r, token: explorerColour(p.verifiers[r.index]?.colour, r.index) }))
  return {
    quality,
    cost,
    qualityGrid: grid(QH),
    costGrid: grid(CH),
    pass: { y: r1(QH * (1 - passAt / 100)), top: 1 - passAt / 100, label: `pass ${passAt}` },
    rows,
    selected,
    verdict,
    readout: verdict ? `/100 · ${verdict.cost} a run · ${verdict.delta}` : '',
    costMax,
    summary: `Ranked by quality per dollar: ${rows.map((r) => `${r.rank} ${r.name}, score ${r.score}, ${r.cost} a run, ${r.word}`).join('; ')}`,
  }
}

/** Index of the next row in rank order, for arrow keys: `step` 1 down, -1 up; wraps. */
export function explorerStep(rows: readonly Pick<RankRow, 'index'>[], current: number, step: number): number {
  if (!rows.length) return current
  const at = rows.findIndex((r) => r.index === current)
  const next = at < 0 ? 0 : (at + step + rows.length) % rows.length
  return rows[next]?.index ?? current
}

