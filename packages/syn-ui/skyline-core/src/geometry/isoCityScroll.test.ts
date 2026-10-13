import { describe, expect, it } from 'vitest'
import { isoCityHistory, maxMonthOffset, mondayOf, monthsBack, monthsBetween, offsetForWeek, offsetLabel, offsetShowing, weekIndexOf, weekStartAt, windowRange } from './index'

describe('month arithmetic (UTC day keys)', () => {
  it('finds the Monday on or before a day', () => {
    expect(mondayOf('2026-10-09')).toBe('2026-10-05')
    expect(mondayOf('2026-10-05')).toBe('2026-10-05')
    expect(mondayOf('2026-10-11')).toBe('2026-10-05')
    expect(mondayOf('2026-01-01')).toBe('2025-12-29')
  })

  it('steps back whole months, clamping to shorter months', () => {
    expect(monthsBack('2026-10-09', 1)).toBe('2026-09-09')
    expect(monthsBack('2026-03-31', 1)).toBe('2026-02-28')
    expect(monthsBack('2024-03-31', 1)).toBe('2024-02-29')
    expect(monthsBack('2026-05-31', 1)).toBe('2026-04-30')
    expect(monthsBack('2026-01-15', 1)).toBe('2025-12-15')
    expect(monthsBack('2026-10-09', 13)).toBe('2025-09-09')
    expect(monthsBack('2026-10-09', 0)).toBe('2026-10-09')
  })

  it('is unaffected by daylight-saving changes (US Mar 8 / Nov 1, EU Mar 29 / Oct 25)', () => {
    expect(monthsBack('2026-04-08', 1)).toBe('2026-03-08')
    expect(monthsBack('2026-11-25', 1)).toBe('2026-10-25')
    const h = isoCityHistory('2026-11-04', 52)
    // Every week is exactly 7 days, across both changes.
    for (const d of ['2026-03-08', '2026-03-29', '2026-10-25', '2026-11-01']) {
      const w = weekIndexOf(h, d)
      expect(weekStartAt(h, w)).toBe(mondayOf(d))
    }
  })

  it('counts calendar months between two days', () => {
    expect(monthsBetween('2026-10-01', '2026-10-31')).toBe(0)
    expect(monthsBetween('2026-07-31', '2026-10-01')).toBe(3)
    expect(monthsBetween('2025-12-31', '2026-01-01')).toBe(1)
  })
})

describe('window range', () => {
  const h = isoCityHistory('2026-10-09', 52)

  it('ends the history on the week holding today', () => {
    expect(h.start).toBe('2025-10-13')
    expect(weekIndexOf(h, '2026-10-09')).toBe(51)
    expect(weekStartAt(h, 51)).toBe('2026-10-05')
  })

  it('shows the latest weeks at offset 0', () => {
    expect(windowRange(h, 14, 0)).toEqual({ first: 38, last: 51, end: '2026-10-09' })
  })

  it('ends each month step on the whole week holding the same date a month earlier', () => {
    const r = windowRange(h, 14, 1)
    expect(r.end).toBe('2026-09-09')
    expect(weekStartAt(h, r.last)).toBe(mondayOf('2026-09-09'))
    expect(r.last - r.first + 1).toBe(14)
    // A window end always snaps to a whole week: the last day shown is a Sunday.
    for (let n = 0; n < 9; n++) {
      const w = windowRange(h, 14, n)
      expect(new Date(weekStartAt(h, w.last) + 'T00:00:00Z').getUTCDay()).toBe(1)
    }
  })

  it('moves by 4 or 5 weeks per month depending on the month length', () => {
    const steps = Array.from({ length: 8 }, (_, n) => windowRange(h, 14, n).last - windowRange(h, 14, n + 1).last)
    for (const s of steps) expect([4, 5]).toContain(s)
  })

  it('pins at the oldest weeks past the max offset', () => {
    const max = maxMonthOffset(h, 14)
    expect(windowRange(h, 14, max).first).toBe(0)
    expect(windowRange(h, 14, max - 1).first).toBeGreaterThan(0)
    expect(windowRange(h, 14, max + 5)).toMatchObject({ first: 0, last: 13 })
    expect(maxMonthOffset(h, 8)).toBeGreaterThan(max)
  })

  it('keeps the window inside a history shorter than it', () => {
    const short = isoCityHistory('2026-10-09', 5)
    expect(windowRange(short, 14, 0)).toMatchObject({ first: 0, last: 4 })
    expect(maxMonthOffset(short, 14)).toBe(0)
  })
})

describe('scrolling to a week', () => {
  const h = isoCityHistory('2026-10-09', 52)

  it('does not move when the week is in view', () => {
    expect(offsetShowing(h, 14, 45, 0)).toBe(0)
    expect(offsetShowing(h, 14, 38, 0)).toBe(0)
  })

  it('steps the fewest months back or forward to bring a week into view', () => {
    const back = offsetShowing(h, 14, 30, 0)
    const r = windowRange(h, 14, back)
    expect(r.first).toBeLessThanOrEqual(30)
    expect(windowRange(h, 14, back - 1).first).toBeGreaterThan(30)
    const fwd = offsetShowing(h, 14, 51, 6)
    expect(windowRange(h, 14, fwd).last).toBe(51)
    expect(fwd).toBe(0)
  })

  it('jumps to a week strip week inside the window of its own month', () => {
    for (let w = 0; w < 52; w++) {
      const n = offsetForWeek(h, 14, w)
      const r = windowRange(h, 14, n)
      expect(w).toBeGreaterThanOrEqual(r.first)
      expect(w).toBeLessThanOrEqual(r.last)
    }
    // June 15 is after June 9 (four months before Oct 9), so the June window cannot hold it: the nearest one, July's, does.
    expect(offsetForWeek(h, 14, weekIndexOf(h, '2026-06-15'))).toBe(3)
    expect(offsetForWeek(h, 14, weekIndexOf(h, '2026-06-01'))).toBe(4)
  })

  it('labels the offset', () => {
    expect(offsetLabel(0, 14)).toBe('Latest 14 weeks')
    expect(offsetLabel(1, 14)).toBe('1 month back')
    expect(offsetLabel(5, 8)).toBe('5 months back')
  })
})
