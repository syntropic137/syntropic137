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

/** One row of GET /workflows/{id}/trend (PR #1800). Structural: the API type satisfies it. */
export interface WorkflowTrendRowLike {
  date: string | null
  status?: string | null
  duration_seconds?: number | null
  /** A floor, not a measurement: left out of the trend. */
  duration_is_lower_bound?: boolean
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

const measured = (r: WorkflowTrendRowLike): boolean => !!r.date && !r.duration_is_lower_bound && typeof r.duration_seconds === 'number' && Number.isFinite(r.duration_seconds)

/** Measured durations of dated runs, oldest first (the API sends newest first), the last `window` of them. */
export function recentDurations(rows: readonly WorkflowTrendRowLike[], window = TREND_WINDOW): number[] {
  return rows
    .filter(measured)
    .map((r) => ({ t: Date.parse(r.date ?? ''), d: r.duration_seconds as number }))
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

/** No measured duration: says why, and never "No runs yet" when the card counts runs. */
function emptyTrend(hasRows: boolean, hasRuns: boolean): DurationTrend {
  const word = hasRows ? (hasRuns ? 'No finished runs' : WORD.none) : hasRuns ? 'No trend' : WORD.none
  const label = hasRows ? 'No finished runs yet' : hasRuns ? 'Duration trend not available' : 'No runs yet'
  return { kind: 'none', pct: 0, runs: 0, word, sub: '—', label, spark: sparkPath([]) }
}

/**
 * The card's duration trend. `runsCount` is the run count the same card
 * displays: when it says the workflow has runs, the empty state never reads
 * "No runs yet" (the trend may be missing because the endpoint is not
 * deployed, or no run has finished).
 */
export function durationTrend(rows: readonly WorkflowTrendRowLike[], runsCount?: number): DurationTrend {
  const ds = recentDurations(rows)
  const n = ds.length
  if (n === 0) return emptyTrend(rows.length > 0, (runsCount ?? 0) > 0)
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

/** What a card shows while its trend is loading. */
export const DURATION_TREND_PENDING: DurationTrend = { kind: 'none', pct: 0, runs: 0, word: 'Loading', sub: '', label: 'Loading the duration trend', spark: sparkPath([]) }
