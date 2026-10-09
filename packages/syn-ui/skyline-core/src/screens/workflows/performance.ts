/**
 * Workflow Performance panel (Workflow, PhoneWorkflow boards): "is this
 * workflow getting better?". Four summary cards, one Success / Speed / Cost /
 * Tokens chart with a dot per run coloured by outcome, a run readout and a
 * duration graph per phase, all from the rows of GET /workflows/{id}/trend.
 * Pure: the page passes rows in and renders what comes out.
 */
import { MONTHS } from '../../geometry/skyline'
import { axisTicks, linePath, niceCeil, sparkPath, timeX, valueY } from '../../geometry/trend'
import type { TrendDot, TrendEnd, TrendLine, TrendNote, TrendTick } from '../../patterns/trendChart'
import { changeNotes, compactTokens, minutesSeconds, shortDay, type DefinitionChangeLike } from '../evals/trend'

/** Runs the Success line averages over. */
export const SUCCESS_WINDOW = 5
/** Completed runs averaged on each side of a summary card's comparison. */
export const KPI_WINDOW = 3
/** Path height the chart lines are drawn for. */
export const PERF_VIEW_HEIGHT = 200

const DAY = 86_400_000

export interface WorkflowTrendPhaseLike {
  phase_id: string
  phase_name: string
  duration_seconds: number | null
}

/** One row of GET /workflows/{id}/trend. Structural: the API type satisfies it. */
export interface PerfRowLike {
  execution_id: string
  date: string | null
  status: string
  cost_usd: number | string | null
  cost_display?: string
  duration_seconds: number | null
  duration_is_lower_bound?: boolean
  duration_display?: string
  tokens: number
  phase_durations?: readonly WorkflowTrendPhaseLike[]
}

export type PerfMetric = 'success' | 'speed' | 'cost' | 'tokens'
export type PerfOutcome = 'completed' | 'failed' | 'cancelled' | 'other'
export type PerfWord = 'Improving' | 'Regressing' | 'Flat'
export type PerfTone = 'good' | 'bad' | 'neutral'

export const PERF_METRICS: readonly { value: PerfMetric; label: string }[] = [
  { value: 'success', label: 'Success' },
  { value: 'speed', label: 'Speed' },
  { value: 'cost', label: 'Cost' },
  { value: 'tokens', label: 'Tokens' },
]

export function parsePerfMetric(raw: string | null | undefined): PerfMetric {
  return raw === 'success' || raw === 'speed' || raw === 'tokens' ? raw : 'cost'
}

export interface PerfRun {
  i: number
  t: number
  x: number
  outcome: PerfOutcome
  /** Completed with a measured duration: counted by Speed, Cost and Tokens. */
  counted: boolean
  cost: number
  seconds: number
  tokens: number
  /** Rolling share of completed runs over the last SUCCESS_WINDOW, 0-100. */
  ok: number
  executionId: string
  costDisplay: string
  speedDisplay: string
  phases: readonly WorkflowTrendPhaseLike[]
}

export interface PerfKpi {
  label: string
  value: string
  delta: string
  word: PerfWord
  tone: PerfTone
}

export interface PhaseDurationGraph {
  key: string
  name: string
  now: string
  delta: string
  tone: PerfTone
  spark: string
  label: string
}

export interface PerfReadout {
  date: string
  id: string
  executionId: string
  status: PerfOutcome
  statusWord: string
  speed: string
  cost: string
  success: string
  x: number
}

export interface PerformanceModel {
  empty: boolean
  runs: PerfRun[]
  metric: PerfMetric
  title: string
  unit: string
  subtitle: string
  kpis: PerfKpi[]
  lines: TrendLine[]
  dots: TrendDot[]
  ends: TrendEnd[]
  yTicks: TrendTick[]
  xTicks: TrendTick[]
  notes: TrendNote[]
  phases: PhaseDurationGraph[]
  /** Run index the readout starts on: the latest run. */
  initial: number
}

// ---- formatting ---------------------------------------------------------

const num = (v: number | string | null | undefined): number => {
  const n = typeof v === 'number' ? v : Number(v ?? NaN)
  return Number.isFinite(n) ? n : 0
}
const cost3 = (v: number) => `$${Math.abs(v).toFixed(3)}`
const pct = (v: number) => `${Math.round(v)}%`

export function perfOutcome(status: string | null | undefined): PerfOutcome {
  const s = (status ?? '').toLowerCase()
  if (s === 'completed' || s === 'succeeded' || s === 'success') return 'completed'
  if (s === 'failed' || s === 'error') return 'failed'
  if (s === 'cancelled' || s === 'canceled' || s === 'interrupted') return 'cancelled'
  return 'other'
}

const OUTCOME_WORD: Record<PerfOutcome, string> = { completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled', other: 'In progress' }

/** "Sep 8, 2026" in UTC. */
export function longDay(t: number): string {
  const d = new Date(t)
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`
}

// ---- rows -> runs ---------------------------------------------------------

/** Dated rows, oldest first (the API sends newest first), with the rolling success share. */
export function perfRuns(rows: readonly PerfRowLike[]): PerfRun[] {
  const dated = rows
    .flatMap((r) => {
      const t = r.date ? Date.parse(r.date) : NaN
      return Number.isFinite(t) ? [{ r, t }] : []
    })
    .sort((a, b) => a.t - b.t)
  if (dated.length === 0) return []
  const t0 = dated[0]!.t
  const t1 = dated.at(-1)!.t
  const oks: number[] = []
  return dated.map(({ r, t }, i) => {
    const outcome = perfOutcome(r.status)
    // Runs still going are not an outcome yet, so they do not move Success.
    if (outcome !== 'other') oks.push(outcome === 'completed' ? 1 : 0)
    const w = oks.slice(-SUCCESS_WINDOW)
    const seconds = num(r.duration_seconds)
    return {
      i,
      t,
      x: timeX(t, t0, t1),
      outcome,
      counted: outcome === 'completed' && typeof r.duration_seconds === 'number' && !r.duration_is_lower_bound,
      cost: num(r.cost_usd),
      seconds,
      tokens: num(r.tokens),
      ok: w.length ? Math.round((100 * w.reduce((a, b) => a + b, 0)) / w.length) : 0,
      executionId: r.execution_id,
      costDisplay: r.cost_display ?? cost3(num(r.cost_usd)),
      speedDisplay: r.duration_display ?? minutesSeconds(seconds),
      phases: r.phase_durations ?? [],
    }
  })
}

// ---- metrics ----------------------------------------------------------------

interface MetricDef {
  label: string
  unit: string
  better: 'up' | 'down'
  steps: readonly number[]
  value: (r: PerfRun) => number
  /** Which runs the line goes through. */
  inSet: (r: PerfRun) => boolean
  format: (v: number) => string
  tick: (v: number) => string
}

const PERF: Record<PerfMetric, MetricDef> = {
  success: { label: 'Success', unit: `completed, last ${SUCCESS_WINDOW} runs`, better: 'up', steps: [100], value: (r) => r.ok, inSet: (r) => r.outcome !== 'other', format: pct, tick: pct },
  speed: {
    label: 'Speed',
    unit: 'duration of completed runs',
    better: 'down',
    steps: [1, 2, 4, 6, 8, 10, 12, 20, 30, 60, 90, 120].map((m) => m * 60),
    value: (r) => r.seconds,
    inSet: (r) => r.counted,
    format: minutesSeconds,
    tick: (v) => (v === 0 ? '0' : v % 60 ? minutesSeconds(v) : `${v / 60}m`),
  },
  cost: {
    label: 'Cost',
    unit: 'per completed run',
    better: 'down',
    steps: [0.1, 0.2, 0.3, 0.5, 1, 2, 5, 10, 20, 50],
    value: (r) => r.cost,
    inSet: (r) => r.counted,
    format: cost3,
    tick: (v) => `$${v.toFixed(v >= 10 ? 0 : 2)}`,
  },
  tokens: {
    label: 'Tokens',
    unit: 'per completed run',
    better: 'down',
    steps: [100e3, 200e3, 300e3, 400e3, 600e3, 1e6, 2e6, 5e6, 10e6, 20e6, 50e6],
    value: (r) => r.tokens,
    inSet: (r) => r.counted,
    format: compactTokens,
    tick: (v) => (v === 0 ? '0' : compactTokens(v)),
  },
}

const avg = (xs: readonly number[]) => (xs.length ? xs.reduce((a, v) => a + v, 0) / xs.length : 0)

export function median(xs: readonly number[]): number {
  if (!xs.length) return 0
  const s = [...xs].sort((a, b) => a - b)
  const m = s.length >> 1
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2
}

function judge(diff: number, better: 'up' | 'down'): { word: PerfWord; tone: PerfTone } {
  const good = better === 'up' ? diff > 0 : diff < 0
  const bad = better === 'up' ? diff < 0 : diff > 0
  return good ? { word: 'Improving', tone: 'good' } : bad ? { word: 'Regressing', tone: 'bad' } : { word: 'Flat', tone: 'neutral' }
}

function kpi(label: string, now: number, then: number, fmt: (v: number) => string, better: 'up' | 'down', since: string, dfmt: (v: number) => string = fmt, fresh = false): PerfKpi {
  if (fresh) return { label, value: fmt(now), delta: 'first runs', word: 'Flat', tone: 'neutral' }
  const diff = now - then
  const shown = dfmt(Math.abs(diff))
  // A change that rounds to nothing is no change.
  const zero = diff === 0 || shown === dfmt(0)
  return { label, value: fmt(now), delta: zero ? 'no change' : `${diff > 0 ? '+' : '−'}${shown} ${since}`, ...(zero ? { word: 'Flat' as const, tone: 'neutral' as const } : judge(diff, better)) }
}

/** The four summary cards: latest window against the first one. */
export function perfKpis(runs: readonly PerfRun[]): PerfKpi[] {
  const finished = runs.filter((r) => r.outcome !== 'other')
  const done = runs.filter((r) => r.counted)
  const first = done.slice(0, KPI_WINDOW)
  const last = done.slice(-KPI_WINDOW)
  const fresh = done.length < KPI_WINDOW * 2
  const okNow = finished.at(-1)?.ok ?? 0
  const okThen = finished[Math.min(SUCCESS_WINDOW, finished.length) - 1]?.ok ?? okNow
  return [
    kpi(`Success, last ${SUCCESS_WINDOW}`, okNow, okThen, pct, 'up', `vs first ${SUCCESS_WINDOW} runs`, (v) => `${Math.round(v)} pts`, finished.length <= SUCCESS_WINDOW),
    kpi('Median duration', median(last.map((r) => r.seconds)), median(first.map((r) => r.seconds)), minutesSeconds, 'down', 'vs first runs', minutesSeconds, fresh),
    kpi('Cost per run', avg(last.map((r) => r.cost)), avg(first.map((r) => r.cost)), cost3, 'down', 'vs first runs', cost3, fresh),
    kpi('Tokens per run', avg(last.map((r) => r.tokens)), avg(first.map((r) => r.tokens)), compactTokens, 'down', 'vs first runs', compactTokens, fresh),
  ]
}

/** A duration graph per phase over completed runs, with the latest window against the first. */
export function phaseDurationGraphs(runs: readonly PerfRun[]): PhaseDurationGraph[] {
  const done = runs.filter((r) => r.counted)
  const order: { key: string; name: string }[] = []
  for (const r of done) for (const p of r.phases) if (!order.some((o) => o.key === p.phase_id)) order.push({ key: p.phase_id, name: p.phase_name })
  return order.map(({ key, name }) => {
    const xs = done.flatMap((r) => {
      const d = r.phases.find((p) => p.phase_id === key)?.duration_seconds
      return typeof d === 'number' && Number.isFinite(d) ? [d] : []
    })
    const a = median(xs.slice(0, KPI_WINDOW))
    const b = median(xs.slice(-KPI_WINDOW))
    const change = a > 0 && xs.length >= KPI_WINDOW * 2 ? Math.round(((b - a) / a) * 100) : null
    const tone: PerfTone = change === null ? 'neutral' : change < -2 ? 'good' : change > 2 ? 'bad' : 'neutral'
    const delta = change === null ? (xs.length ? 'first runs' : 'no runs') : `${change < 0 ? '−' : '+'}${Math.abs(change)}% vs first runs`
    const how = change === null ? '' : change < 0 ? `, ${Math.abs(change)}% faster` : change > 0 ? `, ${change}% slower` : ', steady'
    return { key, name, now: xs.length ? minutesSeconds(b) : '—', delta, tone, spark: sparkPath(xs, 200, 48), label: `${name}: median ${xs.length ? minutesSeconds(b) : 'unknown'}${how}` }
  })
}

function xTicksOf(t0: number, t1: number): TrendTick[] {
  const days = Math.round((t1 - t0) / DAY)
  if (days <= 0) return [{ at: timeX(t0, t0, t1), label: shortDay(t0) }]
  const step = Math.max(1, Math.round(days / 4))
  const out: TrendTick[] = []
  for (let d = 0; d <= days; d += step) out.push({ at: timeX(t0 + d * DAY, t0, t1), label: shortDay(t0 + d * DAY) })
  return out
}

function spanText(t0: number, t1: number): string {
  const days = Math.max(1, Math.round((t1 - t0) / DAY))
  if (days < 14) return `${days} ${days === 1 ? 'day' : 'days'}`
  return days < 60 ? `${Math.round(days / 7)} weeks` : `${Math.round(days / 30)} months`
}

function emptyPerformance(metric: PerfMetric): PerformanceModel {
  const M = PERF[metric]
  return { empty: true, runs: [], metric, title: M.label, unit: M.unit, subtitle: 'No runs yet. Each finished run adds a dot here.', kpis: [], lines: [], dots: [], ends: [], yTicks: [], xTicks: [], notes: [], phases: [], initial: -1 }
}

export function workflowPerformance(rows: readonly PerfRowLike[], metric: PerfMetric = 'cost', changes: readonly DefinitionChangeLike[] = []): PerformanceModel {
  const runs = perfRuns(rows)
  if (runs.length === 0) return emptyPerformance(metric)
  const M = PERF[metric]
  const set = runs.filter(M.inSet)
  const max = metric === 'success' ? 100 : niceCeil(Math.max(0, ...set.map(M.value)) || M.steps[0]!, M.steps)
  const y = (r: PerfRun) => valueY(M.value(r), max)
  const t0 = runs[0]!.t
  const t1 = runs.at(-1)!.t
  const last = set.at(-1)
  const note = metric === 'success' ? '' : ' Failed and cancelled runs sit on the baseline and are not counted.'
  return {
    empty: false,
    runs,
    metric,
    title: M.label,
    unit: M.unit,
    subtitle: `${runs.length} ${runs.length === 1 ? 'run' : 'runs'} over ${spanText(t0, t1)}. ${M.better === 'up' ? 'Higher' : 'Lower'} is better.${note}`,
    kpis: perfKpis(runs),
    lines: [{ key: metric, color: 1, d: linePath(set.map((r) => ({ x: r.x, y: y(r) })), 1000, PERF_VIEW_HEIGHT) }],
    dots: runs.map((r) => {
      const inSet = M.inSet(r)
      return {
        i: r.i,
        x: r.x,
        top: inSet ? 100 - y(r) : 100,
        color: 1,
        tone: r.outcome === 'other' ? 'running' : r.outcome,
        muted: !inSet,
        label: `${shortDay(r.t)}: ${OUTCOME_WORD[r.outcome]}${inSet ? `, ${M.format(M.value(r))}` : ', not counted'}`,
      }
    }),
    ends: last ? [{ key: metric, label: M.format(M.value(last)), color: 1, top: 100 - y(last) }] : [],
    yTicks: axisTicks(max, 4).map((v) => ({ at: 100 - valueY(v, max), label: M.tick(v) })),
    xTicks: xTicksOf(t0, t1),
    notes: changeNotes(changes, t0, t1),
    phases: phaseDurationGraphs(runs),
    initial: runs.length - 1,
  }
}

export function perfReadout(model: PerformanceModel, i: number): PerfReadout | null {
  const r = model.runs[i]
  if (!r) return null
  return {
    date: longDay(r.t),
    id: r.executionId,
    executionId: r.executionId,
    status: r.outcome,
    statusWord: OUTCOME_WORD[r.outcome],
    speed: r.outcome === 'other' ? '—' : r.speedDisplay,
    cost: r.costDisplay,
    success: pct(r.ok),
    x: r.x,
  }
}

/** Previous or next run, wrapping. */
export function stepPerfRun(model: PerformanceModel, i: number, by: 1 | -1): number {
  const n = model.runs.length
  if (!n) return -1
  return (((i < 0 ? n - 1 : i) + by) % n + n) % n
}
