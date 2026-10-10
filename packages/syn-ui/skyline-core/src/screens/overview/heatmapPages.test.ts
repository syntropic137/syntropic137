import { describe, expect, it } from 'vitest'
import { heatmapPages, heatmapToSkylineDays } from './index'

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

describe('failed runs per day', () => {
  it('reads failed_executions only when the API sends it', () => {
    const [a, b] = heatmapToSkylineDays([
      { date: '2026-10-01', count: 3, breakdown: { sessions: 3, executions: 2, failed_executions: 2 } },
      { date: '2026-10-02', count: 1, breakdown: { sessions: 1 } },
    ])
    expect(a?.failed).toBe(2)
    expect(b && 'failed' in b).toBe(false)
  })
})
