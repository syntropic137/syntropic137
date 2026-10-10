/**
 * Executions list (Executions and PhoneExecutions boards): time windows,
 * age groups, the hero's lede and the pagination summary.
 */
import { durationBetween, formatDuration } from '../../format/duration'
import { toTime } from '../../format/shared'
import { statusSemantics } from '../../patterns/status'

export type TimeWindow = '15m' | '1h' | '24h' | '7d' | 'all'

export const TIME_WINDOWS: readonly { value: TimeWindow; label: string }[] = [
  { value: '15m', label: '15m' },
  { value: '1h', label: '1h' },
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: 'all', label: 'All' },
]

const WINDOW_MS: Record<Exclude<TimeWindow, 'all'>, number> = {
  '15m': 15 * 60_000,
  '1h': 3_600_000,
  '24h': 86_400_000,
  '7d': 7 * 86_400_000,
}

/** What the Executions and Sessions lists show with no `?window=` (owner tweak, Oct 8 2026). */
export const DEFAULT_LIST_WINDOW: TimeWindow = '24h'

/** `?window=` -> window; unknown or absent gives `fallback`. */
export function parseTimeWindow(value: string | null | undefined, fallback: TimeWindow = 'all'): TimeWindow {
  return value && (value in WINDOW_MS || value === 'all') ? (value as TimeWindow) : fallback
}

/** The `?window=` value for a chosen window: null (no param) when it is the default. */
export function timeWindowParam(window: string | undefined, fallback: TimeWindow = 'all'): string | null {
  const w = parseTimeWindow(window, fallback)
  return w === fallback ? null : w
}

/** Inclusive lower bound for `started_after`, ISO 8601 with an offset (the API rejects naive bounds); undefined for "all". */
export function timeWindowStart(window: TimeWindow, now: number): string | undefined {
  if (window === 'all') return undefined
  return new Date(now - WINDOW_MS[window]).toISOString()
}

/** Statuses the filter chips offer, in board order (desktop). */
export const EXECUTION_FILTERS: readonly { value: string; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'running', label: 'Running' },
  { value: 'queued', label: 'Queued' },
  { value: 'pending', label: 'Pending' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
]

const DAY = 86_400_000

/** Whole local calendar days from `t`'s day to `now`'s day (DST-safe): 0 today, 1 yesterday. */
export function calendarDaysAgo(t: number, now: number): number {
  const day = (ms: number) => {
    const d = new Date(ms)
    return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())
  }
  return Math.round((day(now) - day(t)) / DAY)
}

/**
 * Group heading for a run's age: "Today", "Yesterday", "This week", "Last
 * week", "6 weeks ago", "3 months ago". Days are local calendar days, so a
 * run from 23:00 last night is "Yesterday" even inside a 24h window.
 */
export function ageGroupTitle(startedAt: string | number | null | undefined, now: number): string {
  const t = toTime(startedAt ?? null)
  if (t === null) return 'Undated'
  const days = calendarDaysAgo(t, now)
  if (days < 1) return 'Today'
  if (days < 2) return 'Yesterday'
  if (days < 7) return 'This week'
  const weeks = Math.floor(days / 7)
  if (weeks < 2) return 'Last week'
  if (weeks < 9) return `${weeks} weeks ago`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months} months ago`
  const years = Math.floor(days / 365)
  return years < 2 ? 'Last year' : `${years} years ago`
}

export interface AgeGroup<T> {
  title: string
  /** "2 runs". */
  count: string
  rows: T[]
}

/** Consecutive rows with the same age heading, in the order given (newest first). */
export function groupByAge<T>(rows: readonly T[], startedAt: (row: T) => string | null | undefined, now: number): AgeGroup<T>[] {
  const groups: AgeGroup<T>[] = []
  for (const row of rows) {
    const title = ageGroupTitle(startedAt(row), now)
    const last = groups[groups.length - 1]
    if (last && last.title === title) last.rows.push(row)
    else groups.push({ title, count: '', rows: [row] })
  }
  for (const g of groups) g.count = `${g.rows.length} ${g.rows.length === 1 ? 'run' : 'runs'}`
  return groups
}

export interface OutcomeTotals {
  total: number
  completed: number
  failed: number
  cancelled: number
  running: number
  queued: number
  pending: number
}

/** Fold the server's status counts into the hero's figures. Aliases (canceled, in_progress) count with their kind. */
export function outcomeTotals(counts: Record<string, number> | null | undefined): OutcomeTotals {
  const c = counts ?? {}
  const get = (...keys: string[]) => keys.reduce((n, k) => n + (c[k] ?? 0), 0)
  return {
    total: Object.values(c).reduce((n, v) => n + v, 0),
    completed: get('completed', 'succeeded'),
    failed: get('failed', 'error'),
    cancelled: get('cancelled', 'canceled', 'interrupted'),
    running: get('running', 'in_progress'),
    queued: get('queued'),
    pending: get('pending', 'not_started'),
  }
}

const runningText = (n: number) => (n === 0 ? 'none running' : `${n} running`)

/** Desktop lede: "Every workflow run, newest first. 75 so far, none running." */
export function executionsLede(t: Pick<OutcomeTotals, 'total' | 'running'>): string {
  if (t.total === 0) return 'Every workflow run, newest first. None yet.'
  return `Every workflow run, newest first. ${t.total} so far, ${runningText(t.running)}.`
}

/** Phone lede: "75 runs, none running now". */
export function executionsLedeShort(t: Pick<OutcomeTotals, 'total' | 'running'>): string {
  return `${t.total} ${t.total === 1 ? 'run' : 'runs'}, ${t.running === 0 ? 'none running now' : `${t.running} running now`}`
}

/** "Showing 1–19 of 75 executions", "Showing 51–75 of 75 failed executions". */
export function listSummary(page: number, pageSize: number, shown: number, total: number, status = 'all'): string {
  const noun = `${status === 'all' ? '' : `${status} `}${total === 1 ? 'execution' : 'executions'}`
  if (shown === 0) return `No ${noun}`
  const from = (Math.max(1, page) - 1) * pageSize + 1
  return `Showing ${from}–${from + shown - 1} of ${total} ${noun}`
}

/** The eval an execution belongs to, as ExecutionSummaryResponse.eval / ExecutionDetailResponse.eval carry it. */
export interface ExecutionEvalLike {
  eval_id: string
  eval_name?: string | null
  association_kind?: string | null
  verdict?: string | null
  score?: number | null
}

export interface EvalBadge {
  label: string
  /** "Eval run of verifier-seed: x (launched) · verdict PASS". */
  title: string
  /** App path of the eval. */
  href: string
}

/** Eval marker for a run row or execution header (feedback 4df2bfc9); null when the run is not part of an eval. */
export function evalBadge(e: ExecutionEvalLike | null | undefined): EvalBadge | null {
  if (!e?.eval_id) return null
  const kind = e.association_kind ? ` (${e.association_kind})` : ''
  const verdict = e.verdict ? ` · verdict ${e.verdict}` : ' · not scored yet'
  return { label: 'Eval', title: `Eval run of ${e.eval_name || e.eval_id}${kind}${verdict}`, href: `/evals/${encodeURIComponent(e.eval_id)}` }
}

/** `?eval=1` <-> the list's in-eval filter. */
export function parseEvalFilter(value: string | null | undefined): boolean {
  return value === '1' || value === 'true'
}

export interface RunDurationLike {
  status: string | null | undefined
  started_at?: string | number | null | undefined
  duration_seconds?: number | null | undefined
  duration_display?: string | null | undefined
}

/**
 * How long a run has taken, in ms. A finished run reports the server's
 * duration; a run still going is measured from its start to `now`, so a
 * ticking `now` keeps it moving (feedback 5ed77fc5). Null when nothing is
 * known.
 */
export function runDurationMs(r: RunDurationLike, now: number): number | null {
  if (!statusSemantics(r.status).terminal) {
    const live = durationBetween(r.started_at, null, now)
    if (live !== null) return live
  }
  return typeof r.duration_seconds === 'number' ? r.duration_seconds * 1000 : null
}

/** The duration column: the server's text for a finished run, a live count for a running one. */
export function runDurationText(r: RunDurationLike, now: number): string {
  if (statusSemantics(r.status).terminal && r.duration_display) return r.duration_display
  const ms = runDurationMs(r, now)
  return ms === null ? '—' : formatDuration(ms)
}
