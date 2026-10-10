import { describe, expect, it } from 'vitest'
import {
  normaliseSeries,
  shippedBarRects,
  shippedBars,
  shippedDays,
  shippedDelta,
  shippedDeltaDisplay,
  shippedTiles,
  shippedTone,
  shippedTotalDisplay,
  shippedUnavailableTiles,
  shippedWindowLine,
  type ShippedInput,
} from './index'

const window = { days: 3, from: '2026-10-07T00:00:00Z', to: '2026-10-09T23:59:59Z' }

describe('shippedDays and normaliseSeries', () => {
  it('lists the window oldest first, ending on `to`', () => {
    expect(shippedDays('2026-10-01', 3)).toEqual(['2026-09-29', '2026-09-30', '2026-10-01'])
    expect(shippedDays('nope', 3)).toEqual([])
    expect(shippedDays('2026-10-01', 0)).toEqual([])
  })
  it('fills missing days with 0, sorts, and drops days outside the window', () => {
    const s = normaliseSeries([{ date: '2026-10-09', value: 5 }, { date: '2026-10-07T00:00:00Z', value: 2 }, { date: '2026-09-01', value: 99 }, { date: '2026-10-08', value: null }], window.to, 3)
    expect(s).toEqual([{ date: '2026-10-07', value: 2 }, { date: '2026-10-08', value: 0 }, { date: '2026-10-09', value: 5 }])
    expect(normaliseSeries(null, window.to, 2)).toEqual([{ date: '2026-10-08', value: 0 }, { date: '2026-10-09', value: 0 }])
  })
})

describe('shippedBars', () => {
  it('scales to the largest day, floors small days at 8 and empty days at 4, marks the newest', () => {
    const bars = shippedBars([{ date: 'a', value: 0 }, { date: 'b', value: 1 }, { date: 'c', value: 50 }, { date: 'd', value: 100 }])
    expect(bars.map((b) => b.height)).toEqual([4, 8, 50, 100])
    expect(bars.map((b) => b.empty)).toEqual([true, false, false, false])
    expect(bars.map((b) => b.current)).toEqual([false, false, false, true])
  })
  it('an all-zero window is all empty bars, never NaN', () => {
    expect(shippedBars([{ date: 'a', value: 0 }, { date: 'b', value: 0 }]).map((b) => [b.height, b.empty])).toEqual([[4, true], [4, true]])
  })
  it('rects stand on the baseline', () => {
    const [r0, r1] = shippedBarRects(shippedBars([{ date: 'a', value: 0 }, { date: 'b', value: 10 }]))
    expect(r0).toEqual({ x: 0, y: 26 - 1.04, width: 8, height: 1.04 })
    expect(r1).toEqual({ x: 10, y: 0, width: 8, height: 26 })
  })
})

describe('delta and tone', () => {
  it('prefers the server delta, else the totals', () => {
    expect(shippedDelta({ total: 10, previous_total: 4, delta: 7 })).toBe(7)
    expect(shippedDelta({ total: 10, previous_total: 4 })).toBe(6)
    expect(shippedDelta({ total: 10 })).toBeNull()
  })
  it('up is better, down is worse, zero or unknown is flat; a down-is-good tile inverts', () => {
    expect(shippedTone(3, 'up')).toBe('better')
    expect(shippedTone(-3, 'up')).toBe('worse')
    expect(shippedTone(0, 'up')).toBe('flat')
    expect(shippedTone(null, 'up')).toBe('flat')
    expect(shippedTone(3, 'down')).toBe('worse')
  })
  it('renders delta_display verbatim, else a relative change, points for a percent tile', () => {
    expect(shippedDeltaDisplay({ total: 1204, previous_total: 872, delta_display: '+38%' }, 'relative')).toBe('+38%')
    expect(shippedDeltaDisplay({ total: 1204, previous_total: 872 }, 'relative')).toBe('+38%')
    expect(shippedDeltaDisplay({ total: 5, previous_total: 8 }, 'relative')).toBe('−38%')
    expect(shippedDeltaDisplay({ total: 3, previous_total: 0 }, 'relative')).toBe('+3')
    expect(shippedDeltaDisplay({ total: 9, previous_total: 6 }, 'absolute')).toBe('+3')
    expect(shippedDeltaDisplay({ total: 84, previous_total: 79 }, 'points')).toBe('+5 pts')
    expect(shippedDeltaDisplay({ total: 84, previous_total: 84 }, 'points')).toBe('±0 pts')
    expect(shippedDeltaDisplay({ total: 84 }, 'points')).toBe('—')
  })
  it('formats totals', () => {
    expect(shippedTotalDisplay(1204, 'count')).toBe('1,204')
    expect(shippedTotalDisplay(83.6, 'percent')).toBe('84%')
  })
})

describe('shippedTiles', () => {
  const input: ShippedInput = {
    window,
    commits: { total: 1204, previous_total: 872, delta: 332, delta_display: '+38%', series: [{ date: '2026-10-09', value: 9 }] },
    prs_opened: null,
    prs_merged: { total: 50, previous_total: 61, delta: -11, delta_display: '−18%', series: [] },
    merge_rate: { total: 84, previous_total: 84, delta: 0, delta_display: '±0 pts', series: [] },
    repos_touched: { total: null, reason: 'No GitHub App installed' },
    reasons: { prs_opened: 'PR events are not recorded' },
  }
  const tiles = shippedTiles(input)
  it('keeps board order and labels', () => {
    expect(tiles.map((t) => t.label)).toEqual(['Commits', 'PRs opened', 'PRs merged', 'Merge rate', 'Repos touched'])
  })
  it('builds an available tile', () => {
    const t = tiles[0]!
    expect(t.available && { total: t.total, delta: t.delta, tone: t.tone, bars: t.bars.length, summary: t.summary }).toEqual({
      total: '1,204', delta: '+38%', tone: 'better', bars: 3, summary: 'Commits: 1,204, +38% vs the 3 days before',
    })
  })
  it('tones worse and flat', () => {
    expect(tiles[2]!.available && tiles[2]!.tone).toBe('worse')
    expect(tiles[3]!.available && tiles[3]!.tone).toBe('flat')
  })
  it('a null tile or a null total is unavailable, with the reason from either place', () => {
    expect(tiles[1]).toEqual({ key: 'prs_opened', label: 'PRs opened', available: false, reason: 'PR events are not recorded' })
    expect(tiles[4]).toEqual({ key: 'repos_touched', label: 'Repos touched', available: false, reason: 'No GitHub App installed' })
  })
  it('a server without the endpoint gets five unavailable tiles', () => {
    expect(shippedUnavailableTiles('404').map((t) => [t.label, t.available, t.reason])).toEqual([
      ['Commits', false, '404'], ['PRs opened', false, '404'], ['PRs merged', false, '404'], ['Merge rate', false, '404'], ['Repos touched', false, '404'],
    ])
  })
  it('header line', () => expect(shippedWindowLine(14)).toBe('Last 14 days, vs the 14 before'))
})
