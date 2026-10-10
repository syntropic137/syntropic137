/**
 * The IsoCity geometry against the boards themselves: runs the reference
 * logic in design/canvas/{Main,PhoneOverview}.dc.html (its renderVals(),
 * including the board's own seeded sample history) and checks that
 * isoCity({ weeks, offset: 0 }) draws the same paths: every row and tone,
 * the floor, future outlines, today's tile and beam, month and weekday
 * labels, the bloom and the leader line. Board data stays in the test.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { ISO_CITY_DESKTOP, ISO_CITY_PHONE, ISO_TONES, isoCity, isoCityWeeks, type IsoCityDims, type SkylineDay } from './index'

interface Faces { side: string; front: string; top: string }
interface Label { tf: string; t: string }
interface BoardSky {
  floor: string
  future: string
  today: string
  glowHot: string
  glowFail: string
  lead: string
  beam: { x: number; y: number }
  mo: Record<string, Label>
  wd: Record<string, Label>
  [row: `r${number}`]: Record<string, Faces>
}
interface BoardCell { key: string; rec: (number | string | boolean)[] | null }

function runBoard(file: string): { sky: BoardSky; days: SkylineDay[] } {
  const url = new URL(`../../../../../design/canvas/${file}.dc.html`, import.meta.url)
  const html = readFileSync(fileURLToPath(url), 'utf8')
  const src = html.slice(html.indexOf('class Component'), html.lastIndexOf('</script>'))
  const hooked = src.replace('const cells = [];', 'const cells = __cells;')
  const cells: BoardCell[] = []
  const Stub = class { props = {}; state = {}; setState() {} }
  const make = new Function('DCLogic', '__cells', `${hooked}; return Component`) as (base: typeof Stub, out: BoardCell[]) => new () => { renderVals(): { sky: BoardSky } }
  const Comp = make(Stub, cells)
  const { sky } = new Comp().renderVals()
  const days = cells.flatMap((c): SkylineDay[] => (c.rec ? [{ date: c.key, sessions: Number(c.rec[1]), executions: Number(c.rec[2]), failed: Number(c.rec[9]) }] : []))
  return { sky, days }
}

const parts = (s: string) => (s === 'M0,0' ? '' : s).split('Z').filter(Boolean).sort()
const orEmpty = (s: string) => s || 'M0,0'

describe.each([
  ['Main', ISO_CITY_DESKTOP],
  ['PhoneOverview', ISO_CITY_PHONE],
] as [string, IsoCityDims][])('isoCity matches the %s board', (file, dims) => {
  const { sky, days } = runBoard(file)
  const weeks = isoCityWeeks(days, '2025-10-13', 52)
  const city = isoCity({ weeks, offset: 0, today: '2026-10-09', dims, pad: 0, selected: days.at(-1)!.date })

  it('draws every row and tone exactly, far rows first', () => {
    expect(city.rows.map((r) => r.row)).toEqual([6, 5, 4, 3, 2, 1, 0])
    for (const row of city.rows) {
      for (const tone of ISO_TONES) {
        const blocks = row.blocks.filter((b) => b.tone === tone)
        const want = sky[`r${row.row}`][tone]!
        expect(orEmpty(blocks.map((b) => b.side).join(''))).toBe(want.side)
        expect(orEmpty(blocks.map((b) => b.front).join(''))).toBe(want.front)
        expect(orEmpty(blocks.map((b) => b.top).join(''))).toBe(want.top)
      }
    }
  })

  it('draws the floor, future, today, bloom and leader line', () => {
    expect(city.floor).toBe(sky.floor)
    expect(orEmpty(city.future)).toBe(sky.future)
    expect(city.today?.tile).toBe(sky.today)
    expect(city.today?.beam).toMatchObject(sky.beam)
    expect(parts(city.glowHot)).toEqual(parts(sky.glowHot))
    expect(parts(city.glowFail)).toEqual(parts(sky.glowFail))
    expect(city.lead).toBe(dims.leadY > 0 ? sky.lead : null)
  })

  it('paints month and weekday labels in the board slots', () => {
    expect(city.months.map((m) => [m.transform, m.text])).toEqual(Object.values(sky.mo).filter((m) => m.t).map((m) => [m.tf, m.t]))
    expect(city.weekdays.map((w) => [w.transform, w.text])).toEqual(Object.values(sky.wd).map((m) => [m.tf, m.t]))
  })
})
