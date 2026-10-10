import { describe, expect, it } from 'vitest'
import {
  ISO_CITY_DESKTOP,
  ISO_CITY_PHONE,
  addDays,
  isoCityCentred,
  isoCityEdgeMask,
  isoCityExtent,
  isoCityFit,
  isoCityFreeWidth,
  ISO_WEEKDAY_LABEL_WIDTH,
  isoCityHistory,
  isoCityWeeks,
  layoutIsoCityFloor,
  type IsoCityDims,
  type SkylineDay,
} from './index'
import type { Point } from './path'

const hist = isoCityHistory('2026-10-10', 52) // a Saturday
const busy: SkylineDay[] = Array.from({ length: 52 * 7 }, (_, i) => ({ date: addDays(hist.start, i), sessions: (i % 30) + 1 })).filter((d) => d.date <= '2026-10-10')
const weeks = isoCityWeeks(busy, hist.start, hist.weeks)
const xs = (d: string) => [...d.matchAll(/(-?[\d.]+),(-?[\d.]+)/g)].map((m): Point => [Number(m[1]), Number(m[2])])

describe.each([
  ['desktop', ISO_CITY_DESKTOP],
  ['phone', ISO_CITY_PHONE],
] as [string, IsoCityDims][])('the current week is a full column, centred (owner, Oct 10) - %s', (_n, raw) => {
  const dims = isoCityCentred(raw)
  const first = hist.weeks - dims.win
  const l = layoutIsoCityFloor({ weeks, first, today: '2026-10-10', dims, pad: 2 })

  it('lays out all seven slots of the current week, flagging the days after today as future', () => {
    const last = l.cells.filter((c) => c.week === hist.weeks - 1)
    expect(last).toHaveLength(7)
    expect(last.filter((c) => c.kind === 'future').map((c) => c.date)).toEqual(['2026-10-11'])
    // Monday at the back: Sunday's future tile sits in front of Saturday (today).
    const sun = last.find((c) => c.date === '2026-10-11')!
    const sat = last.find((c) => c.date === '2026-10-10')!
    expect(sun.depth).toBeLessThan(sat.depth)
    expect(l.blocks.some((b) => b.date === '2026-10-11')).toBe(false)
    expect(l.future.split('M').filter(Boolean)).toHaveLength(1)
  })

  it('never lays out a week after today\'s, even with buffer weeks', () => {
    expect(Math.max(...l.cells.map((c) => c.week))).toBe(hist.weeks - 1)
    expect(l.cells.every((c) => c.date <= '2026-10-11')).toBe(true)
  })

  it('runs the floor across every column: every window cell is a block or a tile', () => {
    const inWin = l.cells.filter((c) => c.inWindow)
    expect(inWin).toHaveLength(dims.win * 7)
    const tiles = (l.floor + l.future).split('M').filter(Boolean).length
    expect(tiles + l.blocks.filter((b) => b.inWindow).length).toBe(dims.win * 7)
  })

  it('centres the window: first and last columns have equal margins within one cell (left of the dock on desktop)', () => {
    const pts = l.blocks.filter((b) => b.inWindow).flatMap((b) => [b.side, b.front, b.top].flatMap(xs)).concat(xs(l.future), xs(l.floor))
    const labels = l.weekdays.map((w) => Number(/matrix\(([-\d. ]+)\)/.exec(w.transform)![1]!.trim().split(' ')[4]) + ISO_WEEKDAY_LABEL_WIDTH)
    const left = Math.min(...pts.map((p) => p[0]))
    const right = Math.max(...pts.map((p) => p[0]), ...labels)
    const free = isoCityFreeWidth(dims)
    // Within a quarter cell (the drawn desktop board is 23 units off).
    expect(Math.abs(left - (free - right))).toBeLessThanOrEqual(dims.ax / 4)
    // The blocks themselves stay inside the free width; only a label may reach past it.
    expect(Math.max(...pts.map((p) => p[0]))).toBeLessThanOrEqual(free + 1)
  })
})

describe('edge mask (owner, Oct 10: fluid scroll)', () => {
  it('is opaque over the window and fades to nothing a week beyond each edge, the same at every depth', () => {
    const d = ISO_CITY_DESKTOP
    const m = isoCityEdgeMask(d)
    expect(m.stops.map((s) => s.opacity)).toEqual([0, 1, 1, 0])
    const off = (p: Point) => {
      const vx = m.x2 - m.x1
      const vy = m.y2 - m.y1
      return ((p[0] - m.x1) * vx + (p[1] - m.y1) * vy) / (vx * vx + vy * vy)
    }
    const at = (c: number, r: number): Point => [d.ox + c * d.ax + r * d.bx, d.oy + c * d.ay + r * d.by]
    // One column, any depth: one offset.
    expect(off(at(3, 0))).toBeCloseTo(off(at(3, 6)), 3)
    expect(off(at(0, 4))).toBeCloseTo(m.stops[1]!.offset, 2)
    expect(off(at(d.win - 1 + d.f, 2))).toBeCloseTo(m.stops[2]!.offset, 2)
  })
})

describe('the board fits its own column (owner, Oct 10: the readout never covers today)', () => {
  it.each([400, 824, 1100, 1464, 2400])('keeps the newest column a full cell inside a %ipx column', (px) => {
    const d = isoCityFit(ISO_CITY_DESKTOP, px)
    const [left, right] = isoCityExtent(d, d.win)
    expect(d.vw).toBeGreaterThanOrEqual(px)
    // One unit is one pixel when the column is at least the board's minimum width.
    if (d.vw === px) expect(right).toBeLessThan(px - d.ax)
    expect(right).toBeLessThanOrEqual(d.vw - d.ax)
    expect(left).toBeGreaterThanOrEqual(d.ax - 1)
    expect(d.leadX).toBe(d.vw)
  })
  it('gives a wider column more weeks, within bounds, and keeps the drawn board unmeasured', () => {
    expect(isoCityFit(ISO_CITY_DESKTOP, 1100).win).toBeGreaterThan(isoCityFit(ISO_CITY_DESKTOP, 824).win)
    expect(isoCityFit(ISO_CITY_DESKTOP, 0).win).toBe(ISO_CITY_DESKTOP.win)
    expect(isoCityFit(ISO_CITY_DESKTOP, 824, 14).win).toBe(14)
  })
})

describe('the board fits its column vertically too (codex review 2 of #1856)', () => {
  // Today a Saturday, so the newest week has a future Sunday in the front row.
  const today = '2026-10-10'
  it.each([824, 1100, 1408, 1464, 2400, 5000])('keeps the newest week\'s front tiles and month labels inside the view box at %ipx', (px) => {
    const d = isoCityFit(ISO_CITY_DESKTOP, px)
    const l = layoutIsoCityFloor({ weeks, first: hist.weeks - d.win, today, dims: d, pad: 0 })
    const ys = [l.future, l.floor, ...l.blocks.map((b) => b.side + b.front)].flatMap((p) => xs(p).map((q) => q[1]))
    expect(Math.max(...ys)).toBeLessThan(d.vh)
    // Month labels sit in front of the floor: their anchor (the matrix translation) is inside too, with room for the text.
    for (const m of l.months.filter((x) => x.inWindow)) {
      const ty = Number(/matrix\(([-\d. ]+)\)/.exec(m.transform)![1]!.trim().split(' ')[5])
      expect(ty).toBeLessThanOrEqual(d.vh - 10)
    }
  })
  it('the 1408px column codex measured now gets fewer weeks than width alone allows', () => {
    const d = isoCityFit(ISO_CITY_DESKTOP, 1408)
    expect(d.win).toBeLessThan(23)
    expect(d.win).toBeGreaterThanOrEqual(14)
  })
})

describe('weekday labels stay inside the view box (no horizontal page scroll)', () => {
  it.each([
    ['phone', isoCityCentred(ISO_CITY_PHONE)],
    ['desktop 824', isoCityFit(ISO_CITY_DESKTOP, 824)],
    ['desktop 1464', isoCityFit(ISO_CITY_DESKTOP, 1464)],
  ] as [string, IsoCityDims][])('%s', (_n, d) => {
    const l = layoutIsoCityFloor({ weeks, first: hist.weeks - d.win, today: '2026-10-10', dims: d, pad: 0 })
    for (const w of l.weekdays) {
      const tx = Number(/matrix\(([-\d. ]+)\)/.exec(w.transform)![1]!.trim().split(' ')[4])
      expect(tx + ISO_WEEKDAY_LABEL_WIDTH, w.text).toBeLessThanOrEqual(d.vw)
    }
  })
})
