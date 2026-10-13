import { describe, expect, it } from 'vitest'
import {
  ISO_CITY_DESKTOP,
  ISO_CITY_PHONE,
  addDays,
  isoCity,
  isoCityHistory,
  isoCityStrip,
  isoCityWeeks,
  isoDayLabel,
  isoHeight,
  isoRangeLabel,
  isoTone,
  layoutIsoCityFloor,
  maxMonthOffset,
  type SkylineDay,
} from './index'

const TODAY = '2026-10-09'
const hist = isoCityHistory(TODAY, 52)
// Every day busy, sessions 1..30 cycling, so every cell is a block.
const busy: SkylineDay[] = Array.from({ length: 52 * 7 }, (_, i) => ({ date: addDays(hist.start, i), sessions: (i % 30) + 1, executions: 4 })).filter((d) => d.date <= TODAY)
const weeks = isoCityWeeks(busy, hist.start, hist.weeks)

describe('tones and heights', () => {
  it('tiers by share of the busiest day, coral only with a known failed count', () => {
    expect(isoTone({ date: TODAY, sessions: 30 }, 100)).toBe('hot')
    expect(isoTone({ date: TODAY, sessions: 10 }, 100)).toBe('mid')
    expect(isoTone({ date: TODAY, sessions: 9 }, 100)).toBe('dim')
    expect(isoTone({ date: TODAY, sessions: 9, executions: 4, failed: 2 }, 100)).toBe('fail')
    expect(isoTone({ date: TODAY, sessions: 9, executions: 5, failed: 2 }, 100)).toBe('dim')
    expect(isoTone({ date: TODAY, sessions: 90, executions: 4 }, 100)).toBe('hot')
    expect(isoTone({ date: TODAY, sessions: 90, executions: 4, failed: null }, 100)).toBe('hot')
  })

  it('scales height by sqrt with a floor', () => {
    expect(isoHeight(100, 100, ISO_CITY_DESKTOP)).toBe(110)
    expect(isoHeight(25, 100, ISO_CITY_DESKTOP)).toBe(55)
    expect(isoHeight(0.01, 100, ISO_CITY_DESKTOP)).toBe(6)
    expect(isoHeight(5, 0, ISO_CITY_PHONE)).toBe(4)
  })

  it('labels a day for screen readers', () => {
    expect(isoDayLabel({ date: '2026-08-03', sessions: 5, failed: 2 })).toBe('Mon, Aug 3: 5 sessions, 2 failed')
    expect(isoDayLabel({ date: '2026-08-04', sessions: 1 })).toBe('Tue, Aug 4: 1 session')
  })
})

describe.each([
  ['desktop', ISO_CITY_DESKTOP],
  ['phone', ISO_CITY_PHONE],
] as const)('floor layout (%s)', (_name, dims) => {
  const max = maxMonthOffset(hist, dims.win)
  const layouts = Array.from({ length: max + 1 }, (_, offset) => isoCity({ weeks, offset, today: TODAY, dims }))

  it('makes a week step wider than a block, so blocks in a row never overlap', () => {
    expect(dims.f * (dims.ax + dims.bx)).toBeLessThan(dims.ax)
    for (const l of layouts) {
      for (const row of l.rows) {
        const boxes = row.blocks.map((b) => b.hit)
        for (let i = 1; i < boxes.length; i++) expect(boxes[i]!.x + 2).toBeGreaterThanOrEqual(boxes[i - 1]!.x + boxes[i - 1]!.width - 2)
      }
    }
  })

  it('draws rows far to near and each row left to right (painter order)', () => {
    for (const l of layouts) {
      // Monday at the back, so it paints first (owner, Oct 10).
      expect(l.rows.map((r) => r.row)).toEqual([0, 1, 2, 3, 4, 5, 6])
      for (const r of l.rows) expect(r.blocks.map((b) => b.column)).toEqual([...r.blocks.map((b) => b.column)].sort((a, b) => a - b))
      expect(l.blocks.map((b) => b.depth)).toEqual([...l.blocks.map((b) => b.depth)].sort((a, b) => b - a))
    }
  })

  it('stacks hit boxes nearer and newer on top, each at least hitmin tall', () => {
    const l = layouts[0]!
    for (const b of l.blocks) {
      expect(b.hit.height).toBeGreaterThanOrEqual(dims.hitmin - 0.01)
      expect(b.z).toBe(10 + (6 - b.depth) + b.column)
    }
    const front = l.blocks.find((b) => b.depth === 0 && b.column === 3)!
    const back = l.blocks.find((b) => b.depth === 6 && b.column === 3)!
    expect(front.z).toBeGreaterThan(back.z)
  })

  it('needs at most five month label slots in any window', () => {
    for (const l of layouts) expect(l.months.filter((m) => m.inWindow).length).toBeLessThanOrEqual(5)
    expect(layouts[0]!.weekdays.map((w) => w.text)).toEqual(['Mon', 'Wed', 'Fri'])
  })

  it('lays out one week either side (hidden edge) and more when asked', () => {
    const l = layouts[1]!
    const cols = new Set(l.blocks.map((b) => b.column))
    expect(Math.min(...cols)).toBe(-1)
    expect(Math.max(...cols)).toBe(dims.win)
    expect(l.blocks.filter((b) => !b.inWindow).every((b) => b.column < 0 || b.column >= dims.win)).toBe(true)
    const wide = isoCity({ weeks, offset: 1, today: TODAY, dims, pad: 4 })
    expect(Math.min(...wide.blocks.map((b) => b.column))).toBe(-4)
    expect(wide.blocks.filter((b) => b.inWindow)).toHaveLength(l.blocks.filter((b) => b.inWindow).length)
  })

  it('lights today and outlines the future at offset 0 only', () => {
    expect(layouts[0]!.today).not.toBeNull()
    expect(layouts[0]!.future).not.toBe('')
    expect(layouts[2]!.today).toBeNull()
    expect(layouts[2]!.future).toBe('')
  })
})

describe('layoutIsoCityFloor with gaps', () => {
  it('turns days with no data into floor tiles and selects only blocks in the window', () => {
    const w = isoCityWeeks([{ date: '2026-10-06', sessions: 3 }], hist.start, hist.weeks)
    const l = layoutIsoCityFloor({ weeks: w, first: 38, today: TODAY, selected: '2026-10-06' })
    expect(l.blocks).toHaveLength(1)
    expect(l.selected?.date).toBe('2026-10-06')
    expect(l.lead).toMatch(/^M[\d.]+,[\d.]+V14H846$/)
    expect(layoutIsoCityFloor({ weeks: w, first: 10, today: TODAY, selected: '2026-10-06' }).selected).toBeNull()
  })
})

describe('week strip', () => {
  it('lights the window, marks failing weeks and ticks months', () => {
    const days: SkylineDay[] = [
      { date: '2026-10-05', sessions: 10 },
      { date: '2026-09-28', sessions: 3, failed: 1 },
      { date: '2025-10-14', sessions: 1 },
    ]
    const s = isoCityStrip(isoCityWeeks(days, hist.start, 52), 38, 14, 1)
    expect(s.bars).toHaveLength(52)
    expect(s.bars[51]).toMatchObject({ tone: 'lit', height: 100, label: 'Week of Oct 5: 10 sessions' })
    expect(s.bars[50]).toMatchObject({ tone: 'fail', height: 30 })
    expect(s.bars[0]).toMatchObject({ tone: 'dim', height: 12 })
    expect(s.bars[1]).toMatchObject({ height: 0 })
    expect(s.windowLeft).toBeCloseTo((38 / 52) * 100, 1)
    expect(s.ticks[0]?.text).toBe('Nov')
    expect(s.ticks.every((t) => t.left > 0 && t.left < 100)).toBe(true)
    expect(isoCityStrip(isoCityWeeks(days, hist.start, 52), 44, 8, 3).ticks.map((t) => t.text)).toEqual(['Jan', 'Apr', 'Jul'])
  })

  it('formats the range', () => {
    expect(isoRangeLabel('2026-07-06', '2026-10-09')).toBe('Jul 6 – Oct 9, 2026')
    expect(isoRangeLabel('2025-12-29', '2026-03-01')).toBe('Dec 29, 2025 – Mar 1, 2026')
  })
})
