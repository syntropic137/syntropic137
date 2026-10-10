import { describe, expect, it } from 'vitest'
import { activeDaysIn, heatmapCoverage, heatmapPages, heatmapPeriod, heatmapToSkylineDays } from './index'

describe('heatmap pages', () => {
  it('pages 13 weeks at a time, newest first, only as far back as needed', () => {
    expect(heatmapPages('2026-10-09', 52, 40)).toEqual([{ start_date: '2026-07-13', end_date: '2026-10-09' }])
    const two = heatmapPages('2026-10-09', 52, 36)
    expect(two).toEqual([
      { start_date: '2026-07-13', end_date: '2026-10-09' },
      { start_date: '2026-04-13', end_date: '2026-07-12' },
    ])
    expect(heatmapPages('2026-10-09', 52, 0)).toHaveLength(4)
    expect(heatmapPages('2026-10-09', 52, 0).at(-1)).toEqual({ start_date: '2025-10-13', end_date: '2026-01-11' })
  })

  it('keeps page boundaries stable as the window scrolls (one cache entry per page)', () => {
    expect(heatmapPages('2026-10-09', 52, 0).slice(0, 2)).toEqual(heatmapPages('2026-10-09', 52, 36))
  })
})

describe('failed runs per day (HeatmapDayBucketResponse.failed)', () => {
  it('reads the top-level failed field the API ships', () => {
    const [a, b, c] = heatmapToSkylineDays([
      { date: '2026-10-01', count: 3, breakdown: { sessions: 3, executions: 2, failed: 2 }, failed: 2 },
      { date: '2026-10-02', count: 1, breakdown: { sessions: 1, executions: 1, failed: 0 }, failed: 0 },
      { date: '2026-10-03', count: 1, breakdown: { sessions: 1 } },
    ])
    expect(a?.failed).toBe(2)
    expect(b?.failed).toBe(0)
    // An API older than the field: unknown, never zero, never coral.
    expect(c && 'failed' in c).toBe(false)
  })

  it('ignores the invented failed_executions and failed_count names', () => {
    const [a] = heatmapToSkylineDays([{ date: '2026-10-01', count: 3, breakdown: { sessions: 3, executions: 2, failed_executions: 2, failed_count: 2 } }])
    expect(a && 'failed' in a).toBe(false)
  })
})

describe('active days over a fixed period (codex review of #1856)', () => {
  const period = heatmapPeriod('2026-10-09', 52)
  it('declares the whole history, first Monday to today', () => {
    expect(period).toEqual({ start_date: '2025-10-13', end_date: '2026-10-09' })
  })
  it('counts active days inside the period only', () => {
    const year = [
      { date: '2025-10-01', sessions: 9 },
      { date: '2025-11-03', sessions: 2 },
      { date: '2026-03-02', sessions: 0 },
      { date: '2026-08-03', sessions: 1 },
      { date: '2026-10-05', sessions: 4 },
    ]
    // Days outside the period (an older API answering wider) never count.
    expect(activeDaysIn(year, period)).toBe(3)
  })
})

describe('heatmap coverage: loaded, loading and failed kept apart from zero (codex review of #1856)', () => {
  it('is ready once the data reaches the oldest wanted page', () => {
    expect(heatmapCoverage({ loadedFrom: '2026-04-13', wantedFrom: '2026-04-13', loading: true, error: undefined })).toEqual({ from: '2026-04-13', state: 'ready' })
  })
  it('is loading while an older page is on its way, keeping what is loaded', () => {
    expect(heatmapCoverage({ loadedFrom: '2026-07-13', wantedFrom: '2026-04-13', loading: true, error: undefined })).toEqual({ from: '2026-07-13', state: 'loading' })
    expect(heatmapCoverage({ loadedFrom: null, wantedFrom: '2026-07-13', loading: true, error: undefined })).toEqual({ from: null, state: 'loading' })
  })
  it('is error when the older page failed, so the page can offer Retry', () => {
    expect(heatmapCoverage({ loadedFrom: '2026-07-13', wantedFrom: '2026-04-13', loading: false, error: new Error('503') })).toEqual({ from: '2026-07-13', state: 'error' })
    // A retry in flight reads as loading again.
    expect(heatmapCoverage({ loadedFrom: '2026-07-13', wantedFrom: '2026-04-13', loading: true, error: new Error('503') }).state).toBe('loading')
  })
})
