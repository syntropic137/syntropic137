/**
 * Month scrolling for the Overview IsoCity (Main and PhoneOverview boards,
 * plan 4d): which weeks of the history the window shows.
 *
 * The history is a grid of whole weeks, Monday first, ending with the week
 * that holds `today`. The window shows `window` weeks of it. `offset` counts
 * months back: offset n ends the window on the same date n months before
 * today (clamped to the end of a shorter month), snapped to the whole week
 * that holds that date. The window keeps its week grid; only where it ends
 * moves. Once the window would start before the history, it pins to the
 * oldest weeks, so every offset past maxMonthOffset() shows the same window.
 *
 * Dates are ISO day keys and all arithmetic is UTC, so the maths is the same
 * in every time zone and across daylight-saving changes.
 */
import { addDays, dayFromMs, dayMs } from './skyline'

const WEEK_MS = 7 * 86_400_000

/** The Monday on or before the day. */
export function mondayOf(day: string): string {
  const dow = new Date(dayMs(day)).getUTCDay()
  return addDays(day, -((dow + 6) % 7))
}

/** The same date `months` months earlier, clamped to the last day of a shorter month. */
export function monthsBack(day: string, months: number): string {
  const d = new Date(dayMs(day))
  const total = d.getUTCFullYear() * 12 + d.getUTCMonth() - months
  const y = Math.floor(total / 12)
  const m = total - y * 12
  const last = new Date(Date.UTC(y, m + 1, 0)).getUTCDate()
  return dayFromMs(Date.UTC(y, m, Math.min(d.getUTCDate(), last)))
}

/** Whole calendar months from `day` back to `today` (0 in the same month). */
export function monthsBetween(day: string, today: string): number {
  const a = new Date(dayMs(day))
  const b = new Date(dayMs(today))
  return (b.getUTCFullYear() - a.getUTCFullYear()) * 12 + (b.getUTCMonth() - a.getUTCMonth())
}

export interface IsoCityHistory {
  /** Monday of the oldest week. */
  start: string
  /** Number of weeks, the last one holding `today`. */
  weeks: number
  today: string
}

/** A history of `weeks` whole weeks ending with the week that holds `today`. */
export function isoCityHistory(today: string, weeks: number): IsoCityHistory {
  const n = Math.max(1, Math.floor(weeks))
  return { start: addDays(mondayOf(today), -7 * (n - 1)), weeks: n, today }
}

/** Index of the week holding `day` (may be negative or past the end). */
export function weekIndexOf(history: IsoCityHistory, day: string): number {
  return Math.floor((dayMs(day) - dayMs(history.start)) / WEEK_MS)
}

/** Monday of week `index`. */
export function weekStartAt(history: IsoCityHistory, index: number): string {
  return addDays(history.start, 7 * index)
}

export interface IsoCityWindowRange {
  /** First and last week index shown, inclusive. */
  first: number
  last: number
  /** The date the window was asked to end on (before snapping). */
  end: string
}

/** The weeks shown at `offset` months back. */
export function windowRange(history: IsoCityHistory, window: number, offset: number): IsoCityWindowRange {
  const size = Math.max(1, Math.min(window, history.weeks))
  const end = monthsBack(history.today, Math.max(0, Math.floor(offset)))
  const last = Math.min(history.weeks - 1, weekIndexOf(history, end))
  const first = last - size + 1
  if (first < 0) return { first: 0, last: size - 1, end }
  return { first, last, end }
}

/** Upper bound on the offset search (100 years of months). */
const OFFSET_CAP = 1200

/** The first offset whose window starts at the oldest week; larger offsets change nothing. */
export function maxMonthOffset(history: IsoCityHistory, window: number): number {
  let n = 0
  while (n < OFFSET_CAP && windowRange(history, window, n).first > 0) n++
  return n
}

const contains = (r: IsoCityWindowRange, week: number) => week >= r.first && week <= r.last

/**
 * The offset that shows `week`, moving as little as possible from `from`:
 * `from` itself when the week is already in view, else the nearest month
 * step toward it. Stepping active days uses this, so the window scrolls
 * only when the day is out of view.
 */
export function offsetShowing(history: IsoCityHistory, window: number, week: number, from: number): number {
  const max = maxMonthOffset(history, window)
  const start = Math.min(max, Math.max(0, from))
  const here = windowRange(history, window, start)
  if (contains(here, week)) return start
  const dir = week < here.first ? 1 : -1
  for (let n = start + dir; n >= 0 && n <= max; n += dir) if (contains(windowRange(history, window, n), week)) return n
  return dir > 0 ? max : 0
}

/** Week strip click: the window of the week's own month, or the nearest one that shows it. */
export function offsetForWeek(history: IsoCityHistory, window: number, week: number): number {
  const max = maxMonthOffset(history, window)
  const n = Math.min(max, Math.max(0, monthsBetween(weekStartAt(history, week), history.today)))
  return offsetShowing(history, window, week, n)
}

/** "Latest 14 weeks", "1 month back", "5 months back". */
export function offsetLabel(offset: number, window: number): string {
  if (offset <= 0) return `Latest ${window} weeks`
  return offset === 1 ? '1 month back' : `${offset} months back`
}
