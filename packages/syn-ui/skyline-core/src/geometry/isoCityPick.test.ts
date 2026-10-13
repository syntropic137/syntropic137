import { describe, expect, it } from 'vitest'
import {
  ISO_CITY_DESKTOP,
  ISO_CITY_PHONE,
  addDays,
  isoCity,
  isoCityHistory,
  isoCityWeeks,
  layoutIsoCityFloor,
  maxMonthOffset,
  pickIsoCityBlock,
  pointInPolygon,
  toViewBox,
  type IsoCityBlock,
  type IsoCityDims,
  type SkylineDay,
} from './index'
import type { Point } from './path'

const TODAY = '2026-10-09'
const hist = isoCityHistory(TODAY, 52)
// Dense history, sessions cycling 1..30 (the codex review's repro data): every cell is a block.
const busy: SkylineDay[] = Array.from({ length: 52 * 7 }, (_, i) => ({ date: addDays(hist.start, i), sessions: (i % 30) + 1 })).filter((d) => d.date <= TODAY)
const weeks = isoCityWeeks(busy, hist.start, hist.weeks)

/** The polygons a block actually paints, read back from its SVG path strings (independent of `faces`). */
const parsed = new WeakMap<IsoCityBlock, { polys: Point[][]; box: [number, number, number, number] }>()
function painted(b: IsoCityBlock): { polys: Point[][]; box: [number, number, number, number] } {
  let p = parsed.get(b)
  if (!p) {
    const polys = [b.side, b.front, b.top].map((d) => [...d.matchAll(/(-?[\d.]+),(-?[\d.]+)/g)].map((m): Point => [Number(m[1]), Number(m[2])]))
    const xs = polys.flat().map((q) => q[0])
    const ys = polys.flat().map((q) => q[1])
    p = { polys, box: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)] }
    parsed.set(b, p)
  }
  return p
}
function covers(b: IsoCityBlock, x: number, y: number): boolean {
  const { polys, box } = painted(b)
  if (x < box[0] || x > box[2] || y < box[1] || y > box[3]) return false
  return polys.some((p) => pointInPolygon(x, y, p))
}

/** What the old rectangles picked: the highest z hit box containing the point. */
function rectPick(blocks: readonly IsoCityBlock[], x: number, y: number): IsoCityBlock | null {
  let best: IsoCityBlock | null = null
  for (const b of blocks) {
    if (!b.inWindow) continue
    const h = b.hit
    if (x >= h.x && x <= h.x + h.width && y >= h.y && y <= h.y + h.height && (!best || b.z >= best.z)) best = b
  }
  return best
}

describe('pointInPolygon', () => {
  it('handles inside, outside and edges', () => {
    const sq: Point[] = [[0, 0], [10, 0], [10, 10], [0, 10]]
    expect(pointInPolygon(5, 5, sq)).toBe(true)
    expect(pointInPolygon(11, 5, sq)).toBe(false)
    expect(pointInPolygon(10, 5, sq)).toBe(true)
  })
})

describe.each([
  ['desktop', ISO_CITY_DESKTOP],
  ['phone', ISO_CITY_PHONE],
] as [string, IsoCityDims][])('visible-surface picking (%s)', (_name, dims) => {
  const offsets = [0, 1, Math.min(3, maxMonthOffset(hist, dims.win))]

  it.each(offsets)('picks the block whose painted surface is on top, sampling every visible block (offset %i)', (offset) => {
    const l = isoCity({ weeks, offset, today: TODAY, dims })
    const shown = l.blocks.filter((b) => b.inWindow)
    let verified = 0
    let rectWrong = 0
    shown.forEach((b) => {
      const later = l.blocks.slice(l.blocks.indexOf(b) + 1).filter((o) => o.inWindow)
      for (let x = b.hit.x; x <= b.hit.x + b.hit.width; x += 2.5) {
        for (let y = b.hit.y; y <= b.hit.y + b.hit.height; y += 2.5) {
          if (!covers(b, x, y) || later.some((o) => covers(o, x, y))) continue
          expect(pickIsoCityBlock(l.blocks, x, y)?.date, `${b.date} at ${x},${y}`).toBe(b.date)
          if (rectPick(l.blocks, x, y)?.date !== b.date) rectWrong++
          verified++
        }
      }
    })
    expect(verified).toBeGreaterThan(shown.length * 3)
    // The rectangles this replaces got some of these visible surfaces wrong.
    expect(rectWrong).toBeGreaterThan(0)
  })

  it('gives an overlapped point to the block painted last, and floor to nothing', () => {
    const l = isoCity({ weeks, offset: 0, today: TODAY, dims })
    const shown = l.blocks.filter((b) => b.inWindow)
    let overlaps = 0
    for (const b of shown) {
      for (let x = b.hit.x; x <= b.hit.x + b.hit.width; x += 3) {
        for (let y = b.hit.y; y <= b.hit.y + b.hit.height; y += 3) {
          const under = shown.filter((o) => covers(o, x, y))
          if (under.length < 2) continue
          overlaps++
          expect(pickIsoCityBlock(l.blocks, x, y)?.date).toBe(under.at(-1)!.date)
        }
      }
    }
    expect(overlaps).toBeGreaterThan(0)
    expect(pickIsoCityBlock(l.blocks, 1, 1)).toBeNull()
  })

  it('never picks the hidden edge weeks', () => {
    const l = isoCity({ weeks, offset: 1, today: TODAY, dims, pad: 2 })
    for (const b of l.blocks.filter((o) => !o.inWindow)) {
      const [x, y] = b.anchor
      expect(pickIsoCityBlock(l.blocks, x, y)?.inWindow ?? true).toBe(true)
    }
  })
})

describe('toViewBox', () => {
  it('maps a client point into view box units', () => {
    expect(toViewBox(150, 60, { left: 100, top: 10, width: 520, height: 165 }, 1040, 330)).toEqual([100, 100])
    expect(toViewBox(1, 1, { left: 0, top: 0, width: 0, height: 0 }, 1040, 330)).toBeNull()
  })
})

describe('weekday axis: Monday at the back, days come forward (owner, Oct 10)', () => {
  // The week of Mon Sep 28 .. Sun Oct 4, every day with data; Saturday very tall.
  const start = '2026-09-28'
  const week: SkylineDay[] = Array.from({ length: 7 }, (_, r) => ({ date: addDays(start, r), sessions: r === 5 ? 400 : 6 }))
  const w = isoCityWeeks(week, hist.start, hist.weeks)
  const first = hist.weeks - ISO_CITY_DESKTOP.win
  const layout = (weekdayAxis?: 'monday-back' | 'monday-front') => layoutIsoCityFloor({ weeks: w, first, today: TODAY, weekdayAxis })
  const on = (l: ReturnType<typeof layout>, date: string) => l.blocks.find((b) => b.date === date)!
  const topCentre = (b: IsoCityBlock): Point => {
    const q = b.faces[2]!
    return [q.reduce((n, p) => n + p[0], 0) / 4, q.reduce((n, p) => n + p[1], 0) / 4]
  }

  it('puts Sunday nearer the viewer (greater screen y) than Monday, and paints it last', () => {
    const l = layout()
    const mon = on(l, start)
    const sun = on(l, addDays(start, 6))
    expect(sun.depth).toBe(0)
    expect(mon.depth).toBe(6)
    expect(sun.faces[1]![0]![1]).toBeGreaterThan(mon.faces[1]![0]![1])
    expect(l.blocks.indexOf(sun)).toBeGreaterThan(l.blocks.indexOf(mon))
    expect(l.rows.map((r) => r.weekday)).toEqual(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
  })

  it('never lets a tall Saturday occlude Sunday\'s top face', () => {
    const l = layout()
    const sat = on(l, addDays(start, 5))
    const sun = on(l, addDays(start, 6))
    const [cx, cy] = topCentre(sun)
    expect(pickIsoCityBlock(l.blocks, cx, cy)?.date).toBe(sun.date)
    for (const [x, y] of sun.faces[2]!) expect(pickIsoCityBlock(l.blocks, x, y)?.date).toBe(sun.date)
    expect(l.blocks.indexOf(sat)).toBeLessThan(l.blocks.indexOf(sun))
    // With the boards' old axis the same Saturday stands in front of Sunday and hides it.
    const old = layout('monday-front')
    const [ox, oy] = topCentre(on(old, sun.date))
    expect(pickIsoCityBlock(old.blocks, ox, oy)?.date).toBe(sat.date)
  })

  it('keeps today\'s tile and beam under today\'s block and the weekday labels on their rows', () => {
    const l = isoCity({ weeks, offset: 0, today: TODAY })
    const today = l.blocks.find((b) => b.date === TODAY)!
    expect(today.depth).toBe(2) // Friday
    expect(l.today!.beam.x + 1.5).toBeCloseTo(today.anchor[0], 1)
    const back = layoutIsoCityFloor({ weeks, first: l.range.first, today: TODAY })
    const front = layoutIsoCityFloor({ weeks, first: l.range.first, today: TODAY, weekdayAxis: 'monday-front' })
    expect(back.weekdays.map((x) => x.text)).toEqual(['Mon', 'Wed', 'Fri'])
    expect(back.weekdays[0]!.transform).not.toBe(front.weekdays[0]!.transform)
  })
})
