/**
 * Eval Trend panel (Eval, PhoneEval boards): "Is it getting better, and at
 * what cost?". Turns GET /evals/{id}/trend rows into chart geometry, the
 * verifier cards, verdict lanes and the run readout. Pure: the page passes
 * rows in and renders what comes out.
 */
import { MONTHS } from '../../geometry/skyline'
import { axisTicks, linePath, niceCeil, spreadEndLabels, timeX, valueY, type TrendPoint } from '../../geometry/trend'
import type { TrendDot, TrendEnd, TrendLine, TrendNote, TrendTick } from '../../patterns/trendChart'
import { normalizeVerdict, type Verdict } from '../../patterns/verdict'
import { shortModel } from './index'

/** A run passes when the judge scores it at or above this. */
export const PASS_SCORE = 70
/** Score points a verifier must move to count as better or worse. */
export const SCORE_MOVE = 3
/** How far back the "then" window of a verifier card reaches, in days. */
export const LOOKBACK_DAYS = 14
/** Runs averaged on each side of a verifier card comparison. */
export const CARD_WINDOW = 3
/** Number of series colours (--sky-color-series-1..N). */
export const SERIES_COLORS = 4

const DAY = 86_400_000

/** One row of GET /evals/{id}/trend. Structural: the API type satisfies it. */
export interface EvalTrendRowLike {
  date: string
  verifier_model: string
  judge_model?: string | null
  score?: number | null
  verdict?: string | null
  cost_usd: number | string
  duration_seconds?: number | null
  tokens?: number | null
  execution_id?: string | null
  definition_version?: string | null
  definition_changed_at?: string | null
}

export type TrendMetric = 'cost' | 'speed' | 'tokens'
export type TrendDirection = 'up' | 'down' | 'flat'
export type TrendTone = 'good' | 'bad' | 'neutral'

export interface TrendSeries {
  key: string
  model: string
  short: string
  /** Colour slot 1..SERIES_COLORS. */
  color: number
}

export interface TrendRun {
  i: number
  t: number
  x: number
  series: number
  verdict: Verdict
  score: number | null
  judge: string | null
  cost: number
  seconds: number
  tokens: number
  executionId: string | null
}

export interface VerifierCard {
  key: string
  model: string
  color: number
  score: string
  scoreDelta: string
  scoreDir: TrendDirection
  scoreTone: TrendTone
  metricLabel: string
  metricValue: string
  metricDelta: string
  metricDir: TrendDirection
  metricTone: TrendTone
  verdict: string
  tone: TrendTone
  label: string
}

export interface VerdictLane {
  key: string
  model: string
  color: number
  ticks: { i: number; x: number; verdict: Verdict; label: string }[]
}

export interface MetricDef {
  label: string
  unit: string
  steps: readonly number[]
  tolerance: number
  value: (r: TrendRun) => number
  format: (v: number) => string
  tick: (v: number) => string
}

export interface EvalTrendModel {
  empty: boolean
  runs: TrendRun[]
  series: TrendSeries[]
  subtitle: string
  judges: string
  metric: MetricDef
  quality: { lines: TrendLine[]; dots: TrendDot[]; ends: TrendEnd[]; ticks: TrendTick[]; pass: number }
  efficiency: { lines: TrendLine[]; dots: TrendDot[]; ends: TrendEnd[]; ticks: TrendTick[] }
  xTicks: TrendTick[]
  notes: TrendNote[]
  cards: VerifierCard[]
  lanes: VerdictLane[]
  /** Run index the readout starts on: the latest scored run. */
  initial: number
}

// ---- formatting ---------------------------------------------------------

/** "Sep 8" in UTC. */
export function shortDay(t: number): string {
  const d = new Date(t)
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`
}

/** 37 -> "37s", 372 -> "6m 12s". */
export function minutesSeconds(seconds: number): string {
  const s = Math.round(Math.abs(seconds))
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}

/** 134_400 -> "134k", 1_234_000 -> "1.23M". */
export function compactTokens(n: number): string {
  const a = Math.abs(n)
  return a >= 1e6 ? `${(a / 1e6).toFixed(2)}M` : `${Math.round(a / 1000)}k`
}

const dollars = (v: number) => `$${Math.abs(v).toFixed(2)}`

export const TREND_METRICS: Record<TrendMetric, MetricDef> = {
  cost: { label: 'Cost', unit: 'per run', steps: [0.4, 0.8, 1.2, 1.6, 2, 3.2], tolerance: 0.02, value: (r) => r.cost, format: dollars, tick: dollars },
  speed: {
    label: 'Speed',
    unit: 'time to verdict',
    steps: [4, 6, 8, 10, 12, 16].map((m) => m * 60),
    tolerance: 10,
    value: (r) => r.seconds,
    format: minutesSeconds,
    tick: (v) => (v === 0 ? '0' : v % 60 ? minutesSeconds(v) : `${v / 60}m`),
  },
  tokens: {
    label: 'Tokens',
    unit: 'per run, all phases',
    steps: [100e3, 200e3, 300e3, 400e3, 600e3, 800e3, 1e6],
    tolerance: 5000,
    value: (r) => r.tokens,
    format: compactTokens,
    tick: (v) => (v === 0 ? '0' : compactTokens(v)),
  },
}

export function parseTrendMetric(raw: string | null | undefined): TrendMetric {
  return raw === 'speed' || raw === 'tokens' ? raw : 'cost'
}

// ---- rows -> runs ---------------------------------------------------------

const num = (v: number | string | null | undefined): number => {
  const n = typeof v === 'number' ? v : Number(v ?? NaN)
  return Number.isFinite(n) ? n : 0
}

/** Series in order of each verifier's first run. */
export function trendSeries(rows: readonly EvalTrendRowLike[]): TrendSeries[] {
  const first = new Map<string, number>()
  for (const r of rows) {
    const t = Date.parse(r.date)
    const seen = first.get(r.verifier_model)
    if (seen === undefined || t < seen) first.set(r.verifier_model, t)
  }
  return [...first.entries()]
    .sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0]))
    .map(([model], k) => ({ key: model, model, short: shortModel(model), color: (k % SERIES_COLORS) + 1 }))
}

function toRun(r: EvalTrendRowLike, i: number, series: number, t0: number, t1: number): TrendRun {
  const t = Date.parse(r.date)
  const score = typeof r.score === 'number' && Number.isFinite(r.score) ? r.score : null
  return {
    i,
    t,
    x: timeX(t, t0, t1),
    series,
    verdict: normalizeVerdict(r.verdict),
    score,
    judge: score === null ? null : (r.judge_model ?? null),
    cost: num(r.cost_usd),
    seconds: num(r.duration_seconds),
    tokens: num(r.tokens),
    executionId: r.execution_id ?? null,
  }
}

function timeSpan(rows: readonly EvalTrendRowLike[]): [number, number] {
  const ts = rows.map((r) => Date.parse(r.date))
  return [Math.min(...ts), Math.max(...ts)]
}

// ---- chart pieces ---------------------------------------------------------

function seriesLines(runs: readonly TrendRun[], series: readonly TrendSeries[], y: (r: TrendRun) => number, h: number): TrendLine[] {
  return series.map((s, si) => {
    const pts: TrendPoint[] = runs.filter((r) => r.series === si).map((r) => ({ x: r.x, y: y(r) }))
    return { key: s.key, color: s.color, d: linePath(pts, 1000, h) }
  })
}

function seriesEnds(runs: readonly TrendRun[], series: readonly TrendSeries[], y: (r: TrendRun) => number): TrendEnd[] {
  const raw = series.flatMap((s, si) => {
    const last = runs.filter((r) => r.series === si).at(-1)
    return last ? [{ key: s.key, top: 100 - y(last) }] : []
  })
  return spreadEndLabels(raw).map((e) => {
    const s = series.find((x) => x.key === e.key)!
    return { key: e.key, label: s.short, color: s.color, top: e.top }
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

/** Change markers: one where definition_version changes, at definition_changed_at when given. */
export function changeNotes(rows: readonly EvalTrendRowLike[], t0: number, t1: number): TrendNote[] {
  const sorted = [...rows].sort((a, b) => Date.parse(a.date) - Date.parse(b.date))
  const out: TrendNote[] = []
  let prev: string | null = null
  for (const r of sorted) {
    const v = r.definition_version ?? null
    if (v === null) continue
    if (prev !== null && v !== prev) {
      const t = Date.parse(r.definition_changed_at ?? r.date)
      out.push({ x: timeX(t, t0, t1), label: `Definition ${v} · ${shortDay(t)}` })
    }
    prev = v
  }
  return out
}

// ---- verifier cards -----------------------------------------------------

const avg = (xs: readonly number[]) => xs.reduce((a, v) => a + v, 0) / xs.length

const direction = (delta: number, tol: number): TrendDirection => (delta > tol ? 'up' : delta < -tol ? 'down' : 'flat')

interface CardChange {
  fresh: boolean
  q: TrendDirection
  e: TrendDirection
}

/** The one-line verdict on a verifier: quality first, then what it costs. */
export function verifierVerdict(c: CardChange): { text: string; tone: TrendTone } {
  if (c.fresh) return { text: 'New verifier, not enough history', tone: 'neutral' }
  if (c.q === 'down') return { text: 'Quality is slipping', tone: 'bad' }
  if (c.q === 'up') return qualityUpVerdict(c.e)
  if (c.e === 'down') return { text: 'Same quality, cheaper', tone: 'good' }
  if (c.e === 'up') return { text: 'Same quality, costs more', tone: 'bad' }
  return { text: 'Holding steady', tone: 'neutral' }
}

function qualityUpVerdict(e: TrendDirection): { text: string; tone: TrendTone } {
  if (e === 'down') return { text: 'Better and cheaper', tone: 'good' }
  if (e === 'up') return { text: 'Better, but costs more', tone: 'neutral' }
  return { text: 'Getting better', tone: 'good' }
}

const signed = (n: number, fmt: (v: number) => string) => `${n > 0 ? '+' : n < 0 ? '−' : '±'}${fmt(n)}`

interface Windows {
  now: TrendRun[]
  then: TrendRun[]
}

function windows(list: readonly TrendRun[], lastT: number): Windows {
  return { now: list.slice(-CARD_WINDOW), then: list.filter((r) => r.t <= lastT - LOOKBACK_DAYS * DAY).slice(-CARD_WINDOW) }
}

function verifierCard(s: TrendSeries, mine: readonly TrendRun[], metric: MetricDef): VerifierCard {
  const lastT = mine.at(-1)?.t ?? 0
  const scored = mine.filter((r) => r.score !== null)
  const sw = windows(scored, lastT)
  const ew = windows(mine, lastT)
  const fresh = sw.then.length === 0 || sw.now.length === 0
  const sNow = sw.now.length ? Math.round(avg(sw.now.map((r) => r.score ?? 0))) : null
  const ds = fresh || sNow === null ? 0 : sNow - Math.round(avg(sw.then.map((r) => r.score ?? 0)))
  const eNow = avg(ew.now.map(metric.value))
  const de = fresh ? 0 : eNow - avg(ew.then.map(metric.value))
  const q = direction(ds, SCORE_MOVE - 1)
  const e = direction(de, metric.tolerance)
  const v = verifierVerdict({ fresh, q, e })
  const since = fresh ? '' : ` since ${shortDay(sw.then.at(-1)!.t)}`
  return {
    key: s.key,
    model: s.model,
    color: s.color,
    score: sNow === null ? '—' : String(sNow),
    scoreDelta: fresh ? 'first runs' : `${signed(ds, (n) => String(Math.abs(n)))}${since}`,
    scoreDir: q,
    scoreTone: q === 'up' ? 'good' : q === 'down' ? 'bad' : 'neutral',
    metricLabel: metric.label,
    metricValue: metric.format(eNow),
    metricDelta: fresh ? 'first runs' : e === 'flat' ? 'flat' : signed(de, metric.format),
    metricDir: e,
    metricTone: e === 'down' ? 'good' : e === 'up' ? 'bad' : 'neutral',
    verdict: v.text,
    tone: v.tone,
    label: `${s.model}: score ${sNow ?? 'none'} of 100, ${metric.label.toLowerCase()} ${metric.format(eNow)}, ${v.text.toLowerCase()}`,
  }
}

// ---- model --------------------------------------------------------------

const VERDICT_WORD: Record<Verdict, string> = { pass: 'Pass', fail: 'Fail', error: 'Error', unscored: 'Unscored' }

function dotsOf(runs: readonly TrendRun[], series: readonly TrendSeries[], y: (r: TrendRun) => number, label: (r: TrendRun, s: TrendSeries) => string): TrendDot[] {
  return runs.map((r) => ({ i: r.i, x: r.x, top: 100 - y(r), color: series[r.series]!.color, label: label(r, series[r.series]!) }))
}

function latestScored(runs: readonly TrendRun[]): number {
  const scored = runs.filter((r) => r.score !== null)
  const pool = scored.length ? scored : runs
  return pool.reduce((best, r) => (r.t > best.t || (r.t === best.t && r.series < best.series) ? r : best), pool[0]!).i
}

const EMPTY_METRIC = TREND_METRICS.cost

function emptyModel(metric: MetricDef): EvalTrendModel {
  return {
    empty: true,
    runs: [],
    series: [],
    subtitle: 'No runs yet. Each run adds a dot here once it finishes.',
    judges: '—',
    metric,
    quality: { lines: [], dots: [], ends: [], ticks: [], pass: 100 - PASS_SCORE },
    efficiency: { lines: [], dots: [], ends: [], ticks: [] },
    xTicks: [],
    notes: [],
    cards: [],
    lanes: [],
    initial: -1,
  }
}

function subtitleOf(runs: readonly TrendRun[], series: readonly TrendSeries[], t0: number, t1: number): string {
  const days = Math.round((t1 - t0) / DAY) + 1
  const n = runs.length
  return `${n} ${n === 1 ? 'run' : 'runs'} in ${days} ${days === 1 ? 'day' : 'days'} across ${series.length} ${series.length === 1 ? 'verifier' : 'verifiers'}. Scores come from the judge model; a run passes at ${PASS_SCORE}.`
}

export function evalTrendModel(rows: readonly EvalTrendRowLike[], metricKey: TrendMetric = 'cost'): EvalTrendModel {
  const metric = TREND_METRICS[metricKey] ?? EMPTY_METRIC
  if (rows.length === 0) return emptyModel(metric)
  const series = trendSeries(rows)
  const [t0, t1] = timeSpan(rows)
  const index = new Map(series.map((s, k) => [s.key, k]))
  const runs = [...rows]
    .sort((a, b) => Date.parse(a.date) - Date.parse(b.date) || (index.get(a.verifier_model) ?? 0) - (index.get(b.verifier_model) ?? 0))
    .map((r, i) => toRun(r, i, index.get(r.verifier_model) ?? 0, t0, t1))
  const scored = runs.filter((r) => r.score !== null)
  const max = niceCeil(Math.max(0, ...runs.map(metric.value)), metric.steps)
  const qy = (r: TrendRun) => valueY(r.score ?? 0, 100)
  const ey = (r: TrendRun) => valueY(metric.value(r), max)
  return {
    empty: false,
    runs,
    series,
    subtitle: subtitleOf(runs, series, t0, t1),
    judges: [...new Set(scored.map((r) => r.judge).filter((j): j is string => !!j))].join(', ') || 'none yet',
    metric,
    quality: {
      lines: seriesLines(scored, series, qy, 200),
      dots: dotsOf(scored, series, qy, (r, s) => `${shortDay(r.t)}, ${s.model}: score ${r.score} of 100, judged by ${r.judge ?? 'unknown'}`),
      ends: seriesEnds(scored, series, qy),
      ticks: [0, 25, 50, 75, 100].map((v) => ({ at: 100 - v, label: String(v) })),
      pass: 100 - PASS_SCORE,
    },
    efficiency: {
      lines: seriesLines(runs, series, ey, 150),
      dots: dotsOf(runs, series, ey, (r, s) => `${shortDay(r.t)}, ${s.model}: ${metric.format(metric.value(r))} ${metric.unit}`),
      ends: seriesEnds(runs, series, ey),
      ticks: axisTicks(max).map((v) => ({ at: 100 - valueY(v, max), label: metric.tick(v) })),
    },
    xTicks: xTicksOf(t0, t1),
    notes: changeNotes(rows, t0, t1),
    cards: series.map((s, si) => verifierCard(s, runs.filter((r) => r.series === si), metric)),
    lanes: series.map((s, si) => ({
      key: s.key,
      model: s.model,
      color: s.color,
      ticks: runs.filter((r) => r.series === si).map((r) => ({ i: r.i, x: r.x, verdict: r.verdict, label: `${shortDay(r.t)}, ${s.model}: ${VERDICT_WORD[r.verdict]}` })),
    })),
    initial: latestScored(runs),
  }
}

// ---- readout ------------------------------------------------------------

export interface TrendReadout {
  i: number
  x: number
  date: string
  model: string
  color: number
  verdict: Verdict
  verdictWord: string
  score: string
  scoreOf: string
  judge: string
  cost: string
  speed: string
  tokens: string
  executionId: string | null
}

export function trendReadout(model: EvalTrendModel, i: number): TrendReadout | null {
  const r = model.runs[i]
  if (!r) return null
  const s = model.series[r.series]!
  return {
    i,
    x: r.x,
    date: `${shortDay(r.t)}, ${new Date(r.t).getUTCFullYear()}`,
    model: s.model,
    color: s.color,
    verdict: r.verdict,
    verdictWord: VERDICT_WORD[r.verdict],
    score: r.score === null ? '—' : String(r.score),
    scoreOf: r.score === null ? 'not scored yet' : `of 100 · pass at ${PASS_SCORE}`,
    judge: r.judge ?? 'waiting for the scorer',
    cost: dollars(r.cost),
    speed: minutesSeconds(r.seconds),
    tokens: compactTokens(r.tokens),
    executionId: r.executionId,
  }
}

/** Previous (-1) or next (+1) run in time order, wrapping at the ends. */
export function stepRun(model: EvalTrendModel, i: number, dir: -1 | 1): number {
  const n = model.runs.length
  if (n === 0) return -1
  return (((i + dir) % n) + n) % n
}

export type { TrendDot, TrendEnd, TrendLine, TrendNote, TrendTick } from '../../patterns/trendChart'
