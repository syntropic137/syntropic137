/**
 * The IsoCity week strip (Main and PhoneOverview boards): the whole history,
 * one bar per week, the visible window lit, month ticks underneath. Bar
 * height is the week's sessions over the busiest week (at least 12% when
 * active); a week is `fail` when failed runs are at least a third of its
 * sessions.
 */
import { MONTHS, dayMs } from './skyline'
import type { IsoCityWeek } from './isoCityFloor'

export type IsoStripTone = 'lit' | 'dim' | 'fail'

export interface IsoStripBar {
  week: number
  start: string
  sessions: number
  failed: number
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

function weekTotals(w: IsoCityWeek): { sessions: number; failed: number } {
  let sessions = 0
  let failed = 0
  for (const d of w.days) {
    if (!d) continue
    sessions += d.sessions
    failed += d.failed ?? 0
  }
  return { sessions, failed }
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

/** Bars, ticks and the lit window for weeks `first` .. `first + window - 1`. */
export function isoCityStrip(weeks: readonly IsoCityWeek[], first: number, window: number, tickEvery = 1): IsoCityStrip {
  const totals = weeks.map(weekTotals)
  const max = Math.max(1, ...totals.map((t) => t.sessions))
  const bars = weeks.map((w, i): IsoStripBar => {
    const t = totals[i]!
    const d = new Date(dayMs(w.start))
    const lit = i >= first && i < first + window
    const tone: IsoStripTone = t.failed > 0 && t.failed * 3 >= t.sessions ? 'fail' : lit ? 'lit' : 'dim'
    return {
      week: i,
      start: w.start,
      sessions: t.sessions,
      failed: t.failed,
      height: t.sessions ? Math.max(12, Math.round((t.sessions / max) * 100)) : 0,
      tone,
      label: `Week of ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}: ${t.sessions} ${t.sessions === 1 ? 'session' : 'sessions'}`,
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
