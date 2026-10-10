import { describe, expect, it } from 'vitest'
import { isoCityHistory, isoCityStrip, isoCityWeeks, isoTone, layoutIsoCityFloor, weekLoadStatus, weekStartAt, type SkylineDay } from './index'

const TODAY = '2026-10-09'
const hist = isoCityHistory(TODAY, 52)

describe('strip failure semantics match the day blocks (codex review of #1856)', () => {
  it('a week whose executions all failed is coral even with many sessions', () => {
    const day: SkylineDay = { date: '2026-10-05', sessions: 100, executions: 2, failed: 2 }
    expect(isoTone(day, 100)).toBe('fail')
    const s = isoCityStrip(isoCityWeeks([day], hist.start, 52), 38, 14)
    expect(s.bars[51]).toMatchObject({ tone: 'fail', sessions: 100, executions: 2, failed: 2 })
  })

  it('aggregates executions and failed per week and applies the half rule', () => {
    const days: SkylineDay[] = [
      { date: '2026-09-28', sessions: 1, executions: 3, failed: 1 },
      { date: '2026-09-29', sessions: 1, executions: 3, failed: 2 },
      { date: '2026-09-21', sessions: 50, executions: 10, failed: 4 },
    ]
    const s = isoCityStrip(isoCityWeeks(days, hist.start, 52), 38, 14)
    expect(s.bars[50]).toMatchObject({ executions: 6, failed: 3, tone: 'fail' })
    expect(s.bars[49]).toMatchObject({ executions: 10, failed: 4, tone: 'lit' })
  })

  it('a week with no failed count is never coral', () => {
    const s = isoCityStrip(isoCityWeeks([{ date: '2026-10-05', sessions: 3, executions: 0 }], hist.start, 52), 38, 14)
    expect(s.bars[51]!.tone).toBe('lit')
  })
})

describe('unloaded history is not zero (codex review of #1856)', () => {
  const days: SkylineDay[] = [{ date: '2026-10-05', sessions: 4 }]
  const weeks = isoCityWeeks(days, hist.start, 52)
  const from = weekStartAt(hist, 26)

  it('labels weeks before the loaded range not loaded, loading or did not load', () => {
    const ready = isoCityStrip(weeks, 38, 14, 1, { from, state: 'ready' })
    expect(ready.bars[0]).toMatchObject({ status: 'unloaded', tone: 'unknown', height: 0, label: 'Week of Oct 13: not loaded' })
    expect(ready.bars[26]).toMatchObject({ status: 'loaded', label: `Week of ${'Apr 13'}: 0 sessions` })
    expect(isoCityStrip(weeks, 38, 14, 1, { from, state: 'loading' }).bars[25]!.label).toMatch(/: loading$/)
    expect(isoCityStrip(weeks, 38, 14, 1, { from, state: 'error' }).bars[25]).toMatchObject({ status: 'error', label: expect.stringMatching(/: did not load$/) })
    expect(isoCityStrip(weeks, 38, 14, 1, { from: null, state: 'loading' }).bars.every((b) => b.status === 'loading')).toBe(true)
  })

  it('says 0 sessions only for a loaded, quiet week; no coverage means all loaded', () => {
    const s = isoCityStrip(weeks, 38, 14)
    expect(s.bars.every((b) => b.status === 'loaded')).toBe(true)
    expect(s.bars[0]!.label).toBe('Week of Oct 13: 0 sessions')
    expect(weekLoadStatus('2026-01-05', { from: '2026-01-05', state: 'error' })).toBe('loaded')
    expect(weekLoadStatus('2025-12-29', { from: '2026-01-05', state: 'error' })).toBe('error')
  })

  it('paints unloaded days as unknown tiles, not empty floor', () => {
    const l = layoutIsoCityFloor({ weeks, first: 20, today: TODAY, loadedFrom: from })
    expect(l.unloaded).not.toBe('')
    const all = layoutIsoCityFloor({ weeks, first: 20, today: TODAY })
    expect(all.unloaded).toBe('')
    expect(l.floor.length).toBeLessThan(all.floor.length)
  })
})
