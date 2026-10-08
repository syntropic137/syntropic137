/**
 * Workflow duration trend (Workflows, PhoneWorkflows boards): the card's
 * sparkline and its Faster / Slower / Steady label, from the rows of
 * GET /workflows/{id}/trend.
 */
import { linearFit, sparkPath } from '../../geometry/trend'

/** Runs the label looks back over. */
export const TREND_WINDOW = 12
/** Fewer finished runs than this read "Too few runs". */
export const TREND_MIN_RUNS = 3
/** A fitted change smaller than this, in percent, reads "Steady". */
export const STEADY_PCT = 5

/** One row of GET /workflows/{id}/trend. Structural: the API type satisfies it. */
export interface WorkflowTrendRowLike {
  date: string
  status?: string | null
  duration_seconds?: number | null
}

export type DurationTrendKind = 'none' | 'few' | 'faster' | 'slower' | 'steady'

export interface DurationTrend {
  kind: DurationTrendKind
  /** Signed fitted change in duration over the window, percent; 0 when not classified. */
  pct: number
  /** Finished runs in the window. */
  runs: number
  word: string
  sub: string
  label: string
  /** Sparkline path in a 200 x 40 viewBox; higher is longer. */
  spark: string
}

/** Durations of finished runs, oldest first, the last `window` of them. */
export function recentDurations(rows: readonly WorkflowTrendRowLike[], window = TREND_WINDOW): number[] {
  return rows
    .filter((r) => typeof r.duration_seconds === 'number' && Number.isFinite(r.duration_seconds))
    .map((r) => ({ t: Date.parse(r.date), d: r.duration_seconds as number }))
    .sort((a, b) => a.t - b.t)
    .slice(-window)
    .map((r) => r.d)
}

/** Fitted percent change from the first to the last run (negative is faster). */
export function durationChangePct(durations: readonly number[]): number {
  const fit = linearFit(durations)
  if (fit.start <= 0) return 0
  return Math.round(((fit.end - fit.start) / fit.start) * 100)
}

export function classifyDuration(pct: number): 'faster' | 'slower' | 'steady' {
  if (Math.abs(pct) < STEADY_PCT) return 'steady'
  return pct < 0 ? 'faster' : 'slower'
}

const WORD: Record<DurationTrendKind, string> = { none: 'No runs yet', few: 'Too few runs', faster: 'Faster', slower: 'Slower', steady: 'Steady' }
const SIGN = { faster: '−', slower: '+', steady: '±' } as const

export function durationTrend(rows: readonly WorkflowTrendRowLike[]): DurationTrend {
  const ds = recentDurations(rows)
  const n = ds.length
  if (rows.length === 0 || n === 0) {
    return { kind: 'none', pct: 0, runs: 0, word: WORD.none, sub: '—', label: rows.length ? 'No finished runs yet' : 'No runs yet', spark: sparkPath([]) }
  }
  if (n < TREND_MIN_RUNS) {
    const runs = `${n} ${n === 1 ? 'run' : 'runs'}`
    return { kind: 'few', pct: 0, runs: n, word: WORD.few, sub: runs, label: `Duration trend: too few runs to tell (${runs})`, spark: sparkPath(ds) }
  }
  const pct = durationChangePct(ds)
  const kind = classifyDuration(pct)
  const size = Math.abs(pct)
  const how = kind === 'steady' ? 'steady' : `${size}% ${kind}`
  return {
    kind,
    pct,
    runs: n,
    word: WORD[kind],
    sub: `${SIGN[kind]}${size}% time, last ${n}`,
    label: `Duration trend: ${how} over the last ${n} runs`,
    spark: sparkPath(ds),
  }
}
