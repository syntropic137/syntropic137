/**
 * The IsoCity week strip (Main and PhoneOverview boards): the whole history,
 * one bar per week, the visible window lit, month ticks underneath. Bar
 * height is the week's sessions over the busiest week (at least 12% when
 * active); a week is `fail` by the same rule as a day block (isFailing:
 * failed executions known, at least one, and at least half the week's
 * executions).
 *
 * History the page has not loaded yet is not zero: weeks before
 * `coverage.from` are `unknown`, labelled not loaded, loading or did not
 * load (codex review of #1856).
 */
import { MONTHS, dayMs } from './skyline'
import { isFailing, type IsoCityWeek } from './isoCityFloor'

export type IsoStripTone = 'lit' | 'dim' | 'fail' | 'unknown'

/** Where an unloaded week stands: never asked for, on its way, or failed. */
export type IsoLoadStatus = 'loaded' | 'unloaded' | 'loading' | 'error'

/**
 * How much of the history is loaded. `from` is the first loaded day (null:
 * nothing yet); `state` is the request for older weeks: settled, in flight
 * or failed.
 */
export interface IsoCityCoverage {
  from: string | null
  state: 'ready' | 'loading' | 'error'
}

/** The load status of the week starting on `start` (a Monday). */
export function weekLoadStatus(start: string, coverage: IsoCityCoverage | null | undefined): IsoLoadStatus {
  if (!coverage || (coverage.from !== null && start >= coverage.from)) return 'loaded'
  if (coverage.state === 'loading') return 'loading'
  return coverage.state === 'error' ? 'error' : 'unloaded'
}

const STATUS_TEXT: Record<Exclude<IsoLoadStatus, 'loaded'>, string> = { unloaded: 'not loaded', loading: 'loading', error: 'did not load' }

export interface IsoStripBar {
  week: number
  start: string
  sessions: number
  executions: number
  failed: number
  status: IsoLoadStatus
  /** Percent of the strip height; 0 for a quiet week (drawn as a 2px stub). */
  height: number
  tone: IsoStripTone
  /** "Week of Aug 24: 67 sessions". */
  label: string
}

export interface IsoStripTick {
  /** Percent from the left. */
  left: number
  text: string
}

export interface IsoCityStrip {
  bars: IsoStripBar[]
  ticks: IsoStripTick[]
  /** The lit window, percent from the left and wide. */
  windowLeft: number
  windowWidth: number
}

const pct = (v: number, of: number) => Math.round((v / of) * 10000) / 100

interface WeekTotals {
  sessions: number
  executions: number
  failed: number
}

function weekTotals(w: IsoCityWeek): WeekTotals {
  const t: WeekTotals = { sessions: 0, executions: 0, failed: 0 }
  for (const d of w.days) {
    if (!d) continue
    t.sessions += d.sessions
    t.executions += d.executions ?? 0
    t.failed += d.failed ?? 0
  }
  return t
}

function stripTone(t: WeekTotals, status: IsoLoadStatus, lit: boolean): IsoStripTone {
  if (status !== 'loaded') return 'unknown'
  if (isFailing(t.failed, t.executions)) return 'fail'
  return lit ? 'lit' : 'dim'
}

function barLabel(start: string, t: WeekTotals, status: IsoLoadStatus): string {
  const d = new Date(dayMs(start))
  const head = `Week of ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}: `
  if (status !== 'loaded') return head + STATUS_TEXT[status]
  return head + `${t.sessions} ${t.sessions === 1 ? 'session' : 'sessions'}`
}

function monthOf(start: string): number {
  return new Date(dayMs(start)).getUTCMonth()
}

function ticks(weeks: readonly IsoCityWeek[], tickEvery: number): IsoStripTick[] {
  const out: IsoStripTick[] = []
  let last = -1
  weeks.forEach((w, i) => {
    const m = monthOf(w.start)
    if (m !== last && i > 0 && i < weeks.length - 3 && (tickEvery <= 1 || m % tickEvery === 0)) out.push({ left: pct(i, weeks.length), text: MONTHS[m]! })
    last = m
  })
  return out
}

/** Bars, ticks and the lit window for weeks `first` .. `first + window - 1`; `coverage` marks weeks not loaded yet. */
export function isoCityStrip(weeks: readonly IsoCityWeek[], first: number, window: number, tickEvery = 1, coverage?: IsoCityCoverage | null): IsoCityStrip {
  const totals = weeks.map(weekTotals)
  const max = Math.max(1, ...totals.map((t) => t.sessions))
  const bars = weeks.map((w, i): IsoStripBar => {
    const t = totals[i]!
    const status = weekLoadStatus(w.start, coverage)
    return {
      week: i,
      start: w.start,
      sessions: t.sessions,
      executions: t.executions,
      failed: t.failed,
      status,
      height: status === 'loaded' && t.sessions ? Math.max(12, Math.round((t.sessions / max) * 100)) : 0,
      tone: stripTone(t, status, i >= first && i < first + window),
      label: barLabel(w.start, t, status),
    }
  })
  const n = Math.max(1, weeks.length)
  return { bars, ticks: ticks(weeks, tickEvery), windowLeft: pct(first, n), windowWidth: pct(Math.min(window, n), n) }
}

/** "Jul 6 – Oct 9, 2026", the year on both ends when they differ. */
export function isoRangeLabel(start: string, end: string): string {
  const a = new Date(dayMs(start))
  const b = new Date(dayMs(end))
  const ay = a.getUTCFullYear() !== b.getUTCFullYear() ? `, ${a.getUTCFullYear()}` : ''
  return `${MONTHS[a.getUTCMonth()]} ${a.getUTCDate()}${ay} – ${MONTHS[b.getUTCMonth()]} ${b.getUTCDate()}, ${b.getUTCFullYear()}`
}
