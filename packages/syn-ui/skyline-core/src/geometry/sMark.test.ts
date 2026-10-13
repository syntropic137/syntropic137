import { describe, expect, it } from 'vitest'
import brandSvg from '../../../../../design/brand/s-mark.svg?raw'
import { S_GRID, sMark, type SMarkTone } from './index'

/** "38.64,184 73.28,204" -> "38.6,184.0 73.3,204.0", the brand file's one-decimal format. */
const oneDecimal = (points: string) =>
  points
    .split(' ')
    .map((p) => p.split(',').map((v) => Number(v).toFixed(1)).join(','))
    .join(' ')

/** The brand file's cubes: one <g> per cube, polygons left, right, top. */
function brandCubes(svg: string): { left: string; right: string; top: string; fill: string }[] {
  return [...svg.matchAll(/<g>(.*?)<\/g>/g)].map((g) => {
    const polys = [...(g[1] ?? '').matchAll(/points="([^"]+)" style="fill: ([^"]+)"/g)].map((m) => ({ points: m[1] ?? '', fill: m[2] ?? '' }))
    return { left: polys[0]?.points ?? '', right: polys[1]?.points ?? '', top: polys[2]?.points ?? '', fill: polys[0]?.fill ?? '' }
  })
}

const FRONT_FILL: Record<string, SMarkTone> = { '#4D80FF': 'blue', '#1C2236': 'dark', 'rgba(232,238,251,0.32)': 'glass' }

describe('sMark', () => {
  const mark = sMark(40)

  it('has the grid of the logo: eleven cubes, blue top row with one glass cube', () => {
    expect(S_GRID).toEqual(['BBG', 'B..', 'DDD', '..D', 'DDD'])
    expect(mark.cubes).toHaveLength(11)
    expect(mark.cubes.filter((c) => c.tone === 'blue')).toHaveLength(3)
    expect(mark.cubes.filter((c) => c.tone === 'glass')).toHaveLength(1)
    expect(mark.cubes.find((c) => c.tone === 'glass')).toMatchObject({ column: 2, level: 4 })
  })

  it('reproduces design/brand/s-mark.svg', () => {
    expect(brandSvg).toContain('viewBox="0 0 147 308"')
    expect(mark.viewBox).toBe('0 0 147 308')
    const brand = brandCubes(brandSvg)
    expect(brand).toHaveLength(mark.cubes.length)
    mark.cubes.forEach((c, i) => {
      const b = brand[i]!
      expect(oneDecimal(c.left)).toBe(b.left)
      expect(oneDecimal(c.right)).toBe(b.right)
      expect(oneDecimal(c.top)).toBe(b.top)
      expect(c.tone).toBe(FRONT_FILL[b.fill])
    })
  })

  it('draws back to front, by column then bottom to top', () => {
    expect(mark.cubes.map((c) => c.order)).toEqual([...mark.cubes.keys()])
    expect(mark.cubes.map((c) => `${c.column}${c.level}`)).toEqual(['00', '02', '03', '04', '10', '12', '14', '20', '21', '22', '24'])
  })

  it('scales with the cube size', () => {
    const small = sMark(12, { pad: 0 })
    expect(small.width).toBe(Math.round(4 * 12 * 0.866))
    expect(small.height).toBe(5 * 12 + 5 * 6)
  })
})
