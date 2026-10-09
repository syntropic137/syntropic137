import { describe, expect, it } from 'vitest'
import { STEADY_PCT, classifyDuration, durationChangePct, durationTrend, recentDurations } from './trend'

const day = (d: number) => new Date(Date.UTC(2026, 8, 1 + d)).toISOString()
const rows = (ds: (number | null)[]) => ds.map((d, i) => ({ date: day(i), status: d === null ? 'running' : 'completed', duration_seconds: d }))

describe('workflow duration trend', () => {
  it('keeps finished runs, oldest first, the last twelve', () => {
    const r = rows([...Array.from({ length: 14 }, (_, i) => 100 + i), null])
    expect(recentDurations([...r].reverse())).toEqual(Array.from({ length: 12 }, (_, i) => 102 + i))
  })

  it('measures the fitted change, not the endpoints', () => {
    expect(durationChangePct([100, 90, 80])).toBe(-20)
    expect(durationChangePct([100, 200, 100])).toBe(0)
    expect(durationChangePct([0, 0, 0])).toBe(0)
  })

  it('classifies around the steady band', () => {
    expect(STEADY_PCT).toBe(5)
    expect(classifyDuration(-4)).toBe('steady')
    expect(classifyDuration(4)).toBe('steady')
    expect(classifyDuration(-5)).toBe('faster')
    expect(classifyDuration(6)).toBe('slower')
  })

  it('labels faster, slower and steady like the board', () => {
    const fast = durationTrend(rows([100, 94, 88, 82]))
    expect(fast).toMatchObject({ kind: 'faster', word: 'Faster', sub: '−18% time, last 4', label: 'Duration trend: 18% faster over the last 4 runs' })
    const slow = durationTrend(rows([100, 103, 106]))
    expect(slow).toMatchObject({ kind: 'slower', sub: '+6% time, last 3' })
    const steady = durationTrend(rows([100, 101, 101, 100]))
    expect(steady).toMatchObject({ kind: 'steady', word: 'Steady', sub: '±0% time, last 4', label: 'Duration trend: steady over the last 4 runs' })
  })

  it('says too few runs or no runs', () => {
    expect(durationTrend(rows([100, 90]))).toMatchObject({ kind: 'few', word: 'Too few runs', sub: '2 runs' })
    expect(durationTrend(rows([100]))).toMatchObject({ kind: 'few', sub: '1 run' })
    expect(durationTrend([])).toMatchObject({ kind: 'none', word: 'No runs yet', sub: '—' })
    expect(durationTrend(rows([null]))).toMatchObject({ kind: 'none', label: 'No finished runs yet' })
  })

  it('never says "No runs yet" when the card shows runs (317 runs, trend endpoint 404 on the VPS)', () => {
    const t = durationTrend([], 317)
    expect(t.word).not.toMatch(/No runs/)
    expect(t).toMatchObject({ kind: 'none', word: 'No trend', label: 'Duration trend not available' })
    expect(durationTrend(rows([null]), 3)).toMatchObject({ word: 'No finished runs', label: 'No finished runs yet' })
    expect(durationTrend([], 0)).toMatchObject({ word: 'No runs yet' })
    expect(durationTrend(rows([100, 90, 80]), 317).kind).toBe('faster')
  })
})

describe('workflow duration trend on API rows', () => {
  it('skips undated runs and lower-bound durations', () => {
    const r = [
      { date: day(0), duration_seconds: 100 },
      { date: null, duration_seconds: 5 },
      { date: day(1), duration_seconds: 9, duration_is_lower_bound: true },
      { date: day(2), duration_seconds: 90 },
    ]
    expect(recentDurations(r)).toEqual([100, 90])
  })
})
