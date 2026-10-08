import { describe, expect, it } from 'vitest'
import {
  OBJECT_ICONS,
  OBJECT_KINDS,
  SKYLINE_WEEKS,
  SKYLINE_YEAR,
  describeSkyline,
  fitLabel,
  hitStyle,
  isoBox,
  layoutPhaseBlocks,
  layoutRing,
  layoutSkyline,
  layoutUsageBand,
  obliqueBox,
  percentOf,
  phaseTone,
  recentWeeksRange,
  shareWidths,
  skylineLeadPath,
  verdictBlock,
  weekStart,
  yearRange,
  type SkylineDay,
} from './index'
import { SKYLINE_BOARD_ELEVATION } from './skyline'

// The board numbers below were drawn at the board camera; the shipped default looks down more (skylineView.test.ts).
const BOARD_YEAR = { ...SKYLINE_YEAR, elevation: SKYLINE_BOARD_ELEVATION }
const BOARD_WEEKS = { ...SKYLINE_WEEKS, elevation: SKYLINE_BOARD_ELEVATION }

// The Overview board's eleven active days: date, sessions, executions, cost, input, output, cache write, cache read.
const RAW: [string, number, number, number, number, number, number, number][] = [
  ['2026-07-25', 8, 6, 0.2769, 73903, 8458, 60299, 828266],
  ['2026-07-28', 4, 3, 0.1737, 41859, 7150, 30391, 568180],
  ['2026-08-06', 1, 1, 0, 0, 0, 0, 0],
  ['2026-08-08', 5, 4, 0.043, 17, 279, 29892, 29688],
  ['2026-08-10', 5, 5, 0.1793, 78954, 7729, 0, 617216],
  ['2026-08-17', 3, 2, 0.1258, 29972, 4808, 30385, 326031],
  ['2026-08-21', 10, 6, 0.1324, 62, 4626, 69736, 139626],
  ['2026-08-22', 5, 2, 0.2159, 950, 5038, 70631, 204525],
  ['2026-08-26', 5, 2, 0.1266, 50, 5760, 66436, 82410],
  ['2026-08-27', 19, 11, 0.661, 37111, 21117, 154563, 953286],
  ['2026-08-28', 43, 23, 4.9849, 464027, 137651, 517201, 4556030],
]
const DAYS: SkylineDay[] = RAW.map(([date, sessions, executions, costUsd, input, output, cacheWrite, cacheRead]) => ({
  date,
  sessions,
  executions,
  commits: 0,
  costUsd,
  tokens: { input, output, cacheWrite, cacheRead },
}))
const TODAY = '2026-10-07'

describe('skyline ranges', () => {
  it('starts weeks on Sunday', () => {
    expect(weekStart('2026-01-01')).toBe('2025-12-28')
    expect(weekStart('2026-10-04')).toBe('2026-10-04')
  })
  it('builds the year and the last 16 weeks', () => {
    expect(yearRange(2026)).toEqual({ start: '2026-01-01', end: '2026-12-31' })
    // PhoneOverview: weeks 25..40 of the 2026 grid.
    expect(recentWeeksRange(TODAY, 16)).toEqual({ start: '2026-06-21', end: '2026-10-10' })
  })
})

describe('layoutSkyline, year (Main board)', () => {
  const sky = layoutSkyline({ days: DAYS, range: yearRange(2026), today: TODAY, dims: BOARD_YEAR })

  it('draws one bar per active day, oldest first', () => {
    expect(sky.bars).toHaveLength(11)
    expect(sky.bars.map((b) => b.index)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    expect(sky.maxSessions).toBe(43)
    expect(sky.viewBox).toBe('0 -30 1040 220')
  })

  it('reproduces the tallest bar of the board', () => {
    const top = sky.bars[10]!
    // Aug 28 2026 is a Friday: week 34, depth row 1.
    expect(top.label).toBe('Fri, Aug 28: 43 sessions')
    expect(top.row).toBe(1)
    expect(top.height).toBe(90)
    expect(top.paths).toEqual(obliqueBox({ x: 640, y: 153.5, width: 12, height: 90, dx: 5.6, dy: 4.55 }))
    expect(top.anchor).toEqual({ x: 648.8, y: 61.23 })
    expect(skylineLeadPath(top, 846)).toBe('M648.8,61.23V-14H846')
  })

  it('floors short bars and pads small hit targets', () => {
    const one = sky.bars[2]!
    expect(one.label).toBe('Thu, Aug 6: 1 session')
    expect(one.height).toBe(14)
    expect(one.hit.height).toBeGreaterThanOrEqual(22)
    expect(one.hit.z).toBe(10 - one.row)
    const css = hitStyle(one.hit, SKYLINE_YEAR)
    expect(css.left).toMatch(/%$/)
  })

  it('splits the floor into past, future and month labels', () => {
    expect(sky.floor.length).toBeGreaterThan(0)
    expect(sky.future.length).toBeGreaterThan(0)
    // 365 days: 11 bars, the rest are tiles; Oct 8 to Dec 31 is 85 future days.
    expect(sky.future.split('Z').length - 1).toBe(85)
    expect(sky.floor.split('Z').length - 1).toBe(365 - 85 - 11)
    expect(sky.months.map((m) => [m.label, m.x])).toEqual([
      ['Jan', 20], ['Feb', 110], ['Mar', 182], ['Apr', 254], ['May', 326], ['Jun', 416],
      ['Jul', 488], ['Aug', 560], ['Sep', 650], ['Oct', 722], ['Nov', 812], ['Dec', 884],
    ])
    expect(sky.months[0]!.y).toBe(182)
  })

  it('describes itself', () => {
    expect(describeSkyline(sky, '2026')).toBe(
      'Activity skyline for 2026. 11 active days run from Jul 25 to Aug 28, and Aug 28 is the tallest with 43 sessions.',
    )
    expect(describeSkyline(layoutSkyline({ days: [], range: yearRange(2026), today: TODAY }), '2026')).toMatch(/No sessions yet/)
  })
})

describe('layoutSkyline, 16 weeks (PhoneOverview board)', () => {
  const sky = layoutSkyline({ days: DAYS, range: recentWeeksRange(TODAY), today: TODAY, dims: BOARD_WEEKS })
  it('keeps the global height scale and the board month labels', () => {
    expect(sky.bars).toHaveLength(11)
    expect(sky.bars[10]!.height).toBe(72)
    expect(sky.months.map((m) => [m.label, m.x])).toEqual([['Jul', 25.3], ['Aug', 102.5], ['Sep', 199], ['Oct', 276.2]])
    // Oct 8 to Oct 10 are still to come.
    expect(sky.future.split('Z').length - 1).toBe(3)
  })
  it('ignores days outside the range for drawing but not for scale', () => {
    const only = layoutSkyline({ days: DAYS, range: { start: '2026-07-01', end: '2026-07-31' }, today: TODAY, dims: BOARD_WEEKS })
    expect(only.bars).toHaveLength(2)
    expect(only.maxSessions).toBe(43)
  })
})

describe('layoutPhaseBlocks (Execution board)', () => {
  const layout = layoutPhaseBlocks([
    { name: 'Discovery', durationMs: 24_300, tokens: 93_428, meta: '24.3s · 93.4K tokens · $0.0557', metaShort: '24.3s' },
    { name: 'Deep Dive Analysis', durationMs: 118_900, tokens: 143_918, meta: '118.9s · 143.9K tokens · $0.0798', metaShort: '118.9s' },
    { name: 'Synthesis & Documentation', durationMs: 80_600, tokens: 159_445, meta: '80.6s · 159.4K tokens · $0.0745', metaShort: '80.6s' },
  ])
  it('matches the board coordinates', () => {
    // The board was drawn from unrounded durations; positions agree within 0.15.
    const board = [
      [20, 87.3, 41],
      [115.3, 427.2, 63],
      [550.5, 289.6, 70],
    ]
    layout.blocks.forEach((b, i) => {
      expect(b.x).toBeCloseTo(board[i]![0]!, 0)
      expect(Math.abs(b.width - board[i]![1]!)).toBeLessThanOrEqual(0.15)
      expect(b.height).toBe(board[i]![2])
    })
    expect(layout.blocks[0]!.paths.front).toBe('M20,112L107.3,112L107.3,71L20,71Z')
    expect(layout.blocks[2]!.paths.side).toBe('M840,112L862,98L862,28L840,42Z')
  })
  it('fits labels like the board', () => {
    expect(layout.blocks[0]!.meta?.text).toBe('24.3s')
    expect(layout.blocks[1]!.meta?.text).toBe('118.9s · 143.9K tokens · $0.0798')
    expect(layout.blocks[0]!.number).toEqual({ x: 30, y: 103, text: '01' })
    expect(layout.blocks[2]!.label).toMatchObject({ y: 136, text: 'Synthesis & Documentation' })
  })
  it('keeps pending phases visible', () => {
    const l = layoutPhaseBlocks([
      { name: 'A', durationMs: 60_000, tokens: 1000 },
      { name: 'B', durationMs: null, tokens: null, tone: 'pending' },
    ])
    expect(l.blocks[1]!.width).toBe(28)
    expect(l.blocks[1]!.height).toBe(8)
    expect(l.blocks[1]!.tone).toBe('pending')
  })
  it('maps statuses to tones', () => {
    expect(phaseTone('completed')).toBe('done')
    expect(phaseTone('in_progress')).toBe('running')
    expect(phaseTone('FAILED')).toBe('failed')
    expect(phaseTone('cancelled')).toBe('cancelled')
    expect(phaseTone(undefined)).toBe('pending')
  })
  it('fits and cuts labels', () => {
    expect(fitLabel(['long text here', 'short'], 40, 6)).toBe('short')
    expect(fitLabel(['abcdefghij'], 36, 6)).toBe('abcde…')
    expect(fitLabel([], 100, 6)).toBe('')
  })
  it('shares widths with a floor', () => {
    expect(shareWidths([1, 1], 100, 10)).toEqual([50, 50])
    expect(shareWidths([0, 0, 0], 30, 20)).toEqual([10, 10, 10])
    expect(shareWidths([1000, 1], 100, 10)).toEqual([90, 10])
  })
})

describe('layoutUsageBand (UsageMeter board)', () => {
  it('matches the session band', () => {
    const band = layoutUsageBand([
      { key: 'cacheRead', value: 144_128 },
      { key: 'cacheWrite', value: 0 },
      { key: 'output', value: 1_945 },
      { key: 'input', value: 29_924 },
    ])
    expect(band.segments.map((s) => s.key)).toEqual(['cacheRead', 'output', 'input'])
    const read = band.segments[0]!
    expect(read.width).toBe(799.3)
    expect(read.paths.front).toBe('M0,44L799.3,44L799.3,12L0,12Z')
    expect(read.paths.side).toBe('M799.3,44L815.3,32L815.3,0L799.3,12Z')
    expect(band.segments.map((s) => [s.x, s.width])).toEqual([[0, 799.3], [803.3, 10.8], [818.1, 165.9]])
  })
  it('matches the execution band, with a floor for the 93 input tokens', () => {
    const band = layoutUsageBand([
      { key: 'cacheRead', value: 313_560 },
      { key: 'cacheWrite', value: 64_884 },
      { key: 'output', value: 18_254 },
      { key: 'input', value: 93 },
    ])
    expect(band.segments.map((s) => [s.x, s.width])).toEqual([
      [0, 762],
      [766, 157.7],
      [927.7, 44.4],
      [976.1, 8],
    ])
    expect(band.total).toBe(396_791)
  })
  it('draws nothing for no tokens', () => {
    expect(layoutUsageBand([{ key: 'input', value: 0 }]).segments).toEqual([])
  })
})

describe('layoutRing (Outcomes card)', () => {
  it('matches the board arcs', () => {
    const ring = layoutRing([
      { key: 'completed', value: 50 },
      { key: 'failed', value: 23 },
      { key: 'cancelled', value: 2 },
    ])
    expect(ring.circumference).toBe(289.03)
    const board: [string, number][] = [
      ['189.69 289.03', 0],
      ['85.64 289.03', -192.69],
      ['4.71 289.03', -281.33],
    ]
    ring.arcs.forEach((a, i) => {
      expect(a.dasharray).toBe(board[i]![0])
      expect(a.dashoffset).toBeCloseTo(board[i]![1], 1)
    })
    expect(percentOf(50, 75)).toBe(67)
    expect(percentOf(1, 0)).toBe(0)
  })
  it('closes the ring for a single outcome and draws nothing for none', () => {
    expect(layoutRing([{ key: 'completed', value: 3 }, { key: 'failed', value: 0 }]).arcs[0]!.dasharray).toBe('289.03 289.03')
    expect(layoutRing([{ key: 'completed', value: 0 }]).arcs).toEqual([])
  })
})

describe('verdict blocks and object icons', () => {
  it('reproduces the pass and unscored blocks', () => {
    expect(verdictBlock('pass').top).toBe('M28,18L44,10L28,2L12,10Z')
    expect(verdictBlock('pass').front).toBe('M12,10L28,18L28,42L12,34Z')
    expect(verdictBlock('fail').top).toBe('M28,33L44,25L28,17L12,25Z')
    expect(verdictBlock('unscored').side).toBe('M28,39L44,31L44,34L28,42Z')
  })
  it('defines every object icon from faces only', () => {
    expect(OBJECT_KINDS).toEqual(['trigger', 'workflow', 'execution', 'session', 'artifact', 'eval'])
    const exec = OBJECT_ICONS.execution.groups[0]!.shapes
    expect(exec[0]).toEqual({ el: 'path', d: isoBox({ x: 32, y: 54, width: 20, depth: 20, height: 24 }).top, face: 'top' })
    // The workflow's top slab is the board's diamond.
    const slab = OBJECT_ICONS.workflow.groups[2]!.shapes[0]!
    expect(slab).toEqual({ el: 'path', d: 'M32,28L52,18L32,8L12,18Z', face: 'top' })
    expect(JSON.stringify(OBJECT_ICONS)).not.toMatch(/#[0-9a-f]{3,8}|white|black/i)
  })
})
