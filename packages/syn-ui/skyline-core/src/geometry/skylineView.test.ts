import { describe, expect, it } from 'vitest'
import {
  SKYLINE_BOARD_ELEVATION,
  SKYLINE_ELEVATION,
  SKYLINE_ROW_SPREAD,
  SKYLINE_WEEKS,
  SKYLINE_YEAR,
  layoutSkyline,
  pickSkylineBar,
  projectSkylineDims,
  recentWeeksRange,
  yearRange,
  type SkylineBar,
  type SkylineDay,
  type SkylineDims,
  type SkylineLayout,
} from './skyline'
import { SKYLINE_TONE_FILL, skylineLegend, skylineTone } from './skylineTone'

const TODAY = '2026-10-08'

/** The Overview fixture's heatmap (packages/syn-ui/data/src/fixtures/insights.ts): board days plus a generated tail. */
function fixtureDays(): SkylineDay[] {
  const board: [string, number][] = [
    ['2026-07-25', 8], ['2026-07-28', 4], ['2026-08-06', 1], ['2026-08-08', 5], ['2026-08-10', 5], ['2026-08-17', 3],
    ['2026-08-21', 10], ['2026-08-22', 5], ['2026-08-26', 5], ['2026-08-27', 19], ['2026-08-28', 43],
  ]
  const out: SkylineDay[] = board.map(([date, sessions]) => ({ date, sessions }))
  for (let t = Date.UTC(2026, 8, 1); t <= Date.UTC(2026, 9, 8); t += 86_400_000) {
    const n = new Date(t).getUTCDate()
    if (n % 3 === 0) continue
    out.push({ date: new Date(t).toISOString().slice(0, 10), sessions: ((n * 7) % 13) + 1 })
  }
  return out
}

/**
 * The live VPS heatmap, 2026 sessions per day (GET /insights/contribution-heatmap,
 * 2026-10-09): one 513-session day beside 3-session ones, the shape that hid
 * days behind taller ones at 60 degrees (feedback 75cf7eb2).
 */
const LIVE_2026: [string, number][] = [
  ["2026-04-30", 3], ["2026-05-01", 36], ["2026-05-02", 99], ["2026-05-04", 8], ["2026-08-28", 12], ["2026-08-29", 15],
  ["2026-08-30", 32], ["2026-08-31", 28], ["2026-09-01", 58], ["2026-09-02", 155], ["2026-09-03", 406], ["2026-09-04", 128],
  ["2026-09-05", 194], ["2026-09-06", 8], ["2026-09-07", 3], ["2026-09-08", 179], ["2026-09-09", 92], ["2026-09-10", 16],
  ["2026-09-11", 7], ["2026-09-15", 42], ["2026-09-16", 116], ["2026-09-17", 365], ["2026-09-18", 263], ["2026-09-19", 116],
  ["2026-09-20", 67], ["2026-09-24", 3], ["2026-09-25", 83], ["2026-09-26", 87], ["2026-09-27", 52], ["2026-09-28", 60],
  ["2026-09-29", 5], ["2026-10-01", 8], ["2026-10-02", 61], ["2026-10-03", 96], ["2026-10-04", 234], ["2026-10-05", 385],
  ["2026-10-06", 132], ["2026-10-07", 376], ["2026-10-08", 513], ["2026-10-09", 134],
]
const liveDays = (): SkylineDay[] => LIVE_2026.map(([date, sessions]) => ({ date, sessions }))

/** Share of the bar's top face (a 19 x 19 sample grid) that picks the bar itself. */
function topShare(layout: SkylineLayout, b: SkylineBar, dims: SkylineDims): number {
  const d = projectSkylineDims(dims)
  let hit = 0
  for (let i = 1; i < 20; i++) {
    for (let k = 1; k < 20; k++) {
      const x = b.x + (i / 20) * d.bar + (k / 20) * d.depthX
      const y = b.y - b.height - (k / 20) * d.depthY
      if (pickSkylineBar(layout, x, y) === b) hit++
    }
  }
  return hit / 361
}

/** Does any sampled point of the bar's top face pick the bar itself? */
function topVisible(layout: SkylineLayout, b: SkylineBar, dims: SkylineDims): boolean {
  const d = projectSkylineDims(dims)
  for (let i = 1; i < 10; i++) {
    for (let k = 1; k < 10; k++) {
      const u = i / 10
      const v = k / 10
      const x = b.x + u * d.bar + v * d.depthX
      const y = b.y - b.height - v * d.depthY
      if (pickSkylineBar(layout, x, y) === b) return true
    }
  }
  return false
}

describe('skyline camera tilt', () => {
  it('defaults both presets to the tested elevation, above the board camera', () => {
    expect(SKYLINE_YEAR.elevation).toBe(SKYLINE_ELEVATION)
    expect(SKYLINE_WEEKS.elevation).toBe(SKYLINE_ELEVATION)
    expect(SKYLINE_ELEVATION).toBeGreaterThan(SKYLINE_BOARD_ELEVATION)
    expect(SKYLINE_ELEVATION).toBeLessThan(90)
    expect(SKYLINE_YEAR.rowSpread).toBe(SKYLINE_ROW_SPREAD)
    expect(SKYLINE_ROW_SPREAD).toBeGreaterThan(1)
  })
  it('reproduces the board at the board elevation and flattens bars as it rises', () => {
    const board = projectSkylineDims({ ...SKYLINE_YEAR, elevation: SKYLINE_BOARD_ELEVATION, rowSpread: 1 })
    expect(board.rowDy).toBeCloseTo(SKYLINE_YEAR.rowDy, 9)
    expect(board.maxHeight).toBeCloseTo(SKYLINE_YEAR.maxHeight, 9)
    const tilted = projectSkylineDims(SKYLINE_YEAR)
    expect(tilted.rowDy).toBeGreaterThan(board.rowDy)
    expect(tilted.maxHeight).toBeLessThan(board.maxHeight)
  })
  it('keeps every bar of the fixtures year and 16 weeks inside the viewBox with part of its top in view', () => {
    for (const [dims, range] of [[SKYLINE_YEAR, yearRange(2026)], [SKYLINE_WEEKS, recentWeeksRange(TODAY)]] as const) {
      const layout = layoutSkyline({ days: fixtureDays(), range, today: TODAY, dims })
      expect(layout.bars.length).toBeGreaterThan(20)
      const hidden = layout.bars.filter((b) => !topVisible(layout, b, dims)).map((b) => b.date)
      expect(hidden).toEqual([])
      const top = Math.min(...layout.bars.map((b) => b.anchor.y))
      expect(top).toBeGreaterThan(dims.viewBox.y)
    }
  })
  it('keeps a pickable share of every top face in the fixtures and the pinned live year (feedback 75cf7eb2)', () => {
    for (const [days, min] of [[fixtureDays(), 0.5], [liveDays(), 0.25]] as const) {
      const layout = layoutSkyline({ days, range: yearRange(2026), today: '2026-10-09', dims: SKYLINE_YEAR })
      const worst = Math.min(...layout.bars.map((b) => topShare(layout, b, SKYLINE_YEAR)))
      expect(worst).toBeGreaterThanOrEqual(min)
    }
  })
  it('was not enough at the previous default (60 degrees, board floor): a live day hid completely', () => {
    const dims = { ...SKYLINE_YEAR, elevation: 60, rowSpread: 1 }
    const layout = layoutSkyline({ days: liveDays(), range: yearRange(2026), today: '2026-10-09', dims })
    expect(layout.bars.some((b) => !topVisible(layout, b, dims))).toBe(true)
  })
  it('hides back-row tops at the board elevation (why the default moved)', () => {
    const dims = { ...SKYLINE_YEAR, elevation: SKYLINE_BOARD_ELEVATION, rowSpread: 1 }
    const layout = layoutSkyline({ days: fixtureDays(), range: yearRange(2026), today: TODAY, dims })
    expect(layout.bars.some((b) => !topVisible(layout, b, dims))).toBe(true)
  })
})

describe('pickSkylineBar', () => {
  // Sep 26 2026 (Sat, front row) is short; Sep 27 (Sun, back row of the next week) and Sep 25 (Fri) are tall.
  const days: SkylineDay[] = [
    { date: '2026-09-24', sessions: 40 },
    { date: '2026-09-25', sessions: 43 },
    { date: '2026-09-26', sessions: 2 },
    { date: '2026-09-27', sessions: 43 },
  ]
  for (const dims of [SKYLINE_YEAR, SKYLINE_WEEKS]) {
    const layout = layoutSkyline({ days, range: yearRange(2026), today: TODAY, dims })
    const short = layout.bars.find((b) => b.date === '2026-09-26')!
    const tall = layout.bars.find((b) => b.date === '2026-09-25')!
    it(`resolves a point on a short bar's top face to that day (${dims.viewBox.width} wide)`, () => {
      expect(pickSkylineBar(layout, short.anchor.x, short.anchor.y)?.date).toBe('2026-09-26')
      expect(pickSkylineBar(layout, short.x + 1, short.y - 1)?.date).toBe('2026-09-26')
    })
    it('gives the frontmost face where silhouettes overlap, and nothing on empty ground', () => {
      expect(pickSkylineBar(layout, tall.anchor.x, tall.anchor.y)?.date).toBe('2026-09-25')
      // Just below the short bar's ground line is floor, not a neighbour.
      expect(pickSkylineBar(layout, short.x + 1, short.y + 2)).toBeNull()
    })
  }
})

describe('skylineTone', () => {
  it('colours by outcome mix when the day has outcomes', () => {
    expect(skylineTone({ sessions: 3, outcomes: { passed: 2, failed: 0 } }, 10)).toBe('pass')
    expect(skylineTone({ sessions: 3, outcomes: { passed: 0, failed: 1 } }, 10)).toBe('fail')
    expect(skylineTone({ sessions: 3, outcomes: { passed: 1, failed: 1 } }, 10)).toBe('mixed')
    expect(skylineTone({ sessions: 3, outcomes: { passed: 0, failed: 0 } }, 10)).toBe('none')
  })
  it('falls back to a four-step ramp by session count', () => {
    expect(skylineTone({ sessions: 1, outcomes: null }, 40)).toBe('level-1')
    expect(skylineTone({ sessions: 11, outcomes: null }, 40)).toBe('level-2')
    expect(skylineTone({ sessions: 30, outcomes: null }, 40)).toBe('level-3')
    expect(skylineTone({ sessions: 40 }, 40)).toBe('level-4')
    expect(skylineTone({ sessions: 99 }, 40)).toBe('level-4')
    expect(skylineTone({ sessions: 1 }, 0)).toBe('level-4')
  })
  it('only ever fills from tokens', () => {
    for (const fill of Object.values(SKYLINE_TONE_FILL)) {
      expect(fill).toMatch(/var\(--(sky|ds)-/)
      expect(fill).not.toMatch(/#|rgb|hsl/)
    }
  })
  it('puts the fill on each bar and picks the legend from the data', () => {
    const layout = layoutSkyline({ days: [{ date: '2026-09-02', sessions: 4, outcomes: { passed: 1, failed: 2 } }], range: yearRange(2026), today: TODAY })
    expect(layout.bars[0]).toMatchObject({ tone: 'mixed', fill: 'var(--sky-status-interrupted)' })
    expect(skylineLegend([{ outcomes: null }]).kind).toBe('ramp')
    expect(skylineLegend([{ outcomes: null }, { outcomes: { passed: 1, failed: 0 } }]).items.map((i) => i.tone)).toEqual(['pass', 'mixed', 'fail', 'none'])
  })
})
