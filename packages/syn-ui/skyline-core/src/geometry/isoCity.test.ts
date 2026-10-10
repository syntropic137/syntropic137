import { describe, expect, it } from 'vitest'
import { SAMPLE_SESSIONS, cityActivitySample, isoCity, sampleCityDays, type SkylineDay } from './index'

/** Every coordinate of two point strings within `tol`. */
function close(actual: string, expected: string, tol = 0.11) {
  const a = actual.split(/[ ,]/).map(Number)
  const e = expected.split(/[ ,]/).map(Number)
  expect(a).toHaveLength(e.length)
  a.forEach((v, i) => expect(Math.abs(v - e[i]!)).toBeLessThanOrEqual(tol))
}

describe('isoCity (Landing hero board, desktop)', () => {
  // The board: city(26, 11, 36, live=(150, 171, 199, 222), fails=(88, 260), errs=(141,)).
  const days = sampleCityDays(26, 11, '2026-10-08')
  const city = isoCity(days, { cols: 26, rows: 11, cell: 36, live: [150, 171, 199, 222], failed: [88, 260], errored: [141], maxSessions: SAMPLE_SESSIONS })

  it('has the board viewBox and floor', () => {
    expect(days).toHaveLength(286)
    expect(days.at(-1)?.date).toBe('2026-10-08')
    expect(city.viewBox).toBe('0 0 726 459')
    expect(city.floor).toBe('228,97.5 696,331.5 498,430.5 30,196.5')
    expect(city.blocks).toHaveLength(286)
  })

  it('reproduces the board blocks in draw order', () => {
    // [left, right, top, opacity] from Landing.dc.html, first three and last two.
    const board: [number, string, string, string, number][] = [
      [0, '213.2,101.7 228.0,109.1 228.0,113.9 213.2,106.5', '228.0,109.1 242.8,101.7 242.8,106.5 228.0,113.9', '228.0,94.4 242.8,101.7 228.0,109.1 213.2,101.7', 0.3],
      [1, '195.2,104.1 210.0,111.5 210.0,122.9 195.2,115.5', '210.0,111.5 224.8,104.1 224.8,115.5 210.0,122.9', '210.0,96.8 224.8,104.1 210.0,111.5 195.2,104.1', 0.36],
      [2, '231.2,90.1 246.0,97.5 246.0,122.9 231.2,115.5', '246.0,97.5 260.8,90.1 260.8,115.5 246.0,122.9', '246.0,82.8 260.8,90.1 246.0,97.5 231.2,90.1', 0.5],
      [284, '501.2,369.0 516.0,376.4 516.0,419.9 501.2,412.5', '516.0,376.4 530.8,369.0 530.8,412.5 516.0,419.9', '516.0,361.7 530.8,369.0 516.0,376.4 501.2,369.0', 0.68],
      [285, '483.2,378.5 498.0,385.9 498.0,428.9 483.2,421.5', '498.0,385.9 512.8,378.5 512.8,421.5 498.0,428.9', '498.0,371.1 512.8,378.5 498.0,385.9 483.2,378.5', 0.68],
    ]
    for (const [n, left, right, top, op] of board) {
      const b = city.blocks[n]!
      close(b.left, left)
      close(b.right, right)
      close(b.top, top)
      expect(b.opacity).toBeCloseTo(op, 1)
    }
  })

  it('takes tone from the marked indexes, in the board draw positions', () => {
    const marked = city.blocks.flatMap((b, n) => (b.tone === 'run' ? [] : [[n, b.index, b.tone]]))
    expect(marked.filter(([, , t]) => t === 'failed').map(([n]) => n)).toEqual([55, 95])
    expect(marked.filter(([, , t]) => t === 'live').map(([n]) => n)).toEqual([180, 189, 212, 225])
    expect(marked.find(([, , t]) => t === 'errored')?.[1]).toBe(141)
  })

  it('draws back to front by diagonal', () => {
    const waves = city.blocks.map((b) => b.wave)
    expect(waves).toEqual([...waves].sort((a, b) => a - b))
  })
})

describe('isoCity from real days', () => {
  const days: SkylineDay[] = [
    { date: '2026-10-01', sessions: 0 },
    { date: '2026-10-02', sessions: 10, outcomes: { passed: 3, failed: 0 } },
    { date: '2026-10-03', sessions: 5, outcomes: { passed: 0, failed: 2 } },
    { date: '2026-10-04', sessions: 20, outcomes: { passed: 1, failed: 1 } },
  ]
  const city = isoCity(days, { cols: 2, rows: 3, cell: 20 })
  const byIndex = new Map(city.blocks.map((b) => [b.index, b]))

  it('scales height by the busiest day and leaves empty cells flat', () => {
    expect(byIndex.get(3)).toMatchObject({ activity: 1, height: 3 + 20 * 2.6, date: '2026-10-04' })
    expect(byIndex.get(1)?.activity).toBe(0.5)
    expect(byIndex.get(0)?.height).toBe(3)
    expect(byIndex.get(5)).toMatchObject({ date: null, height: 3, opacity: 0.28 })
  })

  it('reads tone from outcomes', () => {
    expect([0, 1, 2, 3].map((k) => byIndex.get(k)?.tone)).toEqual(['run', 'run', 'failed', 'errored'])
  })

  it('shows the most recent cols x rows days', () => {
    const many = Array.from({ length: 10 }, (_, i): SkylineDay => ({ date: `2026-10-${String(i + 1).padStart(2, '0')}`, sessions: i }))
    const small = isoCity(many, { cols: 2, rows: 2, cell: 10 })
    expect(small.blocks.map((b) => b.date).sort()).toEqual(['2026-10-07', '2026-10-08', '2026-10-09', '2026-10-10'])
  })

  it('samples deterministically', () => {
    expect(cityActivitySample(3, 2)).toEqual(cityActivitySample(3, 2))
    expect(Math.max(...cityActivitySample(26, 11))).toBeLessThanOrEqual(1)
  })
})
