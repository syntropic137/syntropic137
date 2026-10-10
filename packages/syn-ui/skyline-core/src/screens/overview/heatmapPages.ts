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
