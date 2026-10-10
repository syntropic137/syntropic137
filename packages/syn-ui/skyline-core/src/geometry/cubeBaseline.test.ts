/**
 * Output lock for the shared cube primitive (isoCube.ts): every shape built
 * from extruded boxes, captured as exact path strings before the refactor
 * onto isoCube. Any change to a verdict block, object icon, phase block,
 * usage band or skyline bar fails here. Update the snapshot only on purpose.
 */
import { describe, expect, it } from 'vitest'
import {
  OBJECT_ICONS,
  SKYLINE_WEEKS,
  SKYLINE_YEAR,
  isoBox,
  layoutPhaseBlocks,
  layoutSkyline,
  layoutUsageBand,
  obliqueBox,
  obliqueFloor,
  verdictBlock,
  yearRange,
  type SkylineDay,
  type Verdict,
} from './index'

const VERDICTS: Verdict[] = ['pass', 'fail', 'error', 'unscored']

const DAYS: SkylineDay[] = [
  ['2026-07-25', 8],
  ['2026-07-28', 4],
  ['2026-08-06', 1],
  ['2026-08-21', 10],
  ['2026-08-27', 19],
  ['2026-08-28', 43],
].map(([date, sessions]) => ({ date: date as string, sessions: sessions as number, outcomes: { passed: (sessions as number) % 3, failed: (sessions as number) % 2 } }))

describe('cube geometry output lock', () => {
  it('verdict blocks', () => {
    expect(Object.fromEntries(VERDICTS.map((v) => [v, verdictBlock(v)]))).toMatchSnapshot()
  })

  it('object icons', () => {
    expect(OBJECT_ICONS).toMatchSnapshot()
  })

  it('phase blocks', () => {
    const layout = layoutPhaseBlocks([
      { name: 'Discovery', durationMs: 24_300, tokens: 93_428, meta: '24.3s · 93.4K tokens · $0.0557', metaShort: '24.3s' },
      { name: 'Deep Dive Analysis', durationMs: 118_900, tokens: 143_918, meta: '118.9s · 143.9K tokens · $0.0798', metaShort: '118.9s' },
      { name: 'Synthesis & Documentation', durationMs: 80_600, tokens: 159_445, meta: '80.6s · 159.4K tokens · $0.0745', metaShort: '80.6s' },
      { name: 'Pending', durationMs: null, tokens: null, tone: 'pending' },
    ])
    expect(layout).toMatchSnapshot()
  })

  it('usage band', () => {
    const band = layoutUsageBand([
      { key: 'input', value: 93 },
      { key: 'output', value: 137_651 },
      { key: 'cacheWrite', value: 517_201 },
      { key: 'cacheRead', value: 4_556_030 },
    ])
    expect(band.segments).toHaveLength(4)
    expect(band).toMatchSnapshot()
  })

  it('skyline bars and floor tiles', () => {
    const year = layoutSkyline({ days: DAYS, range: yearRange(2026), today: '2026-10-07', dims: SKYLINE_YEAR })
    const weeks = layoutSkyline({ days: DAYS, range: { start: '2026-06-21', end: '2026-10-10' }, today: '2026-10-07', dims: SKYLINE_WEEKS })
    expect(year).toMatchSnapshot()
    expect(weeks).toMatchSnapshot()
  })

  it('raw boxes, including fractional and empty ones', () => {
    expect({
      iso: isoBox({ x: 32, y: 54, width: 20, depth: 20, height: 24 }),
      isoOdd: isoBox({ x: 10.37, y: 41.13, width: 7.3, depth: 11.9, height: 5.55 }),
      isoFlat: isoBox({ x: 0, y: 0, width: 4, depth: 6, height: 0 }),
      oblique: obliqueBox({ x: 20, y: 160, width: 12, height: 30, dx: 5.6, dy: 4.55 }),
      obliqueOdd: obliqueBox({ x: 115.3, y: 112, width: 427.2, height: 63, dx: 22, dy: 14 }),
      obliqueEmpty: obliqueBox({ x: 0, y: 10, width: 12, height: 0, dx: 5, dy: 4 }),
      floor: obliqueFloor({ x: 1.1, y: 2.2, width: 3.3, dx: 4.4, dy: 5.5 }),
    }).toMatchSnapshot()
  })
})
