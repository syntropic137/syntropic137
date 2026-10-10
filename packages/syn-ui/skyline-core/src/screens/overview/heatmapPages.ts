/**
 * Lazy paging of the Overview IsoCity's per-day series. The API takes a
 * date range, so the history is fetched in pages of 13 whole weeks, newest
 * first: page 0 ends today, each older page ends the day before the next
 * one starts. Page boundaries depend only on `today`, so each page is one
 * stable cache entry and scrolling back fetches only the pages it newly
 * needs.
 */
import { addDays } from '../../geometry/skyline'
import { isoCityHistory, weekStartAt } from '../../geometry/isoCityScroll'
import type { IsoCityCoverage } from '../../geometry/isoCityStrip'
import type { SkylineDay } from '../../geometry/skyline'

export const HEATMAP_PAGE_WEEKS = 13

export interface HeatmapPage {
  start_date: string
  end_date: string
}

/** Pages, newest first, that cover the history from week `oldestWeek` (index into the history) to today. */
export function heatmapPages(today: string, historyWeeks: number, oldestWeek: number): HeatmapPage[] {
  const hist = isoCityHistory(today, historyWeeks)
  const want = Math.min(hist.weeks - 1, Math.max(0, Math.floor(oldestWeek)))
  const out: HeatmapPage[] = []
  for (let i = 0; ; i++) {
    const last = hist.weeks - 1 - HEATMAP_PAGE_WEEKS * i
    if (last < 0) break
    const first = Math.max(0, last - HEATMAP_PAGE_WEEKS + 1)
    out.push({ start_date: weekStartAt(hist, first), end_date: i === 0 ? today : addDays(weekStartAt(hist, last), 6) })
    if (first <= want) break
  }
  return out
}

/**
 * The fixed period the headline counts over: the whole declared history,
 * from its first Monday to today. One request, independent of which pages
 * the scroller has loaded (codex review of #1856), so the count never moves
 * when someone scrolls.
 */
export function heatmapPeriod(today: string, historyWeeks: number): HeatmapPage {
  return { start_date: isoCityHistory(today, historyWeeks).start, end_date: today }
}

/** Days with at least one session inside the period (inclusive). */
export function activeDaysIn(days: readonly SkylineDay[], period: HeatmapPage): number {
  return days.filter((d) => d.sessions > 0 && d.date >= period.start_date && d.date <= period.end_date).length
}

export interface HeatmapCoverageInput {
  /** First day of the oldest page in the data the city has (null: no data yet). */
  loadedFrom: string | null
  /** First day of the oldest page the city has asked for. */
  wantedFrom: string
  loading: boolean
  error: unknown
}

/**
 * Loaded, loading or failed, kept apart from zero (codex review of #1856):
 * weeks before `from` are unknown, and `state` says whether the older page
 * is still on its way or failed (the page then offers Retry).
 */
export function heatmapCoverage({ loadedFrom, wantedFrom, loading, error }: HeatmapCoverageInput): IsoCityCoverage {
  if (loadedFrom !== null && loadedFrom <= wantedFrom) return { from: loadedFrom, state: 'ready' }
  if (error !== undefined && error !== null && !loading) return { from: loadedFrom, state: 'error' }
  return { from: loadedFrom, state: 'loading' }
}
