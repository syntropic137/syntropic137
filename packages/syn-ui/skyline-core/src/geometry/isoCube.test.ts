import { describe, expect, it } from 'vitest'
import { ISO_TRUE, isoBox, isoCube, isoCubePoints, obliqueBox, prism, verdictBlock, type Point } from './index'

/** Vertices of an SVG path "M1,2L3,4Z" or a points string "1,2 3,4", as a sorted list of "x,y". */
function vertexSet(s: string): string[] {
  return s
    .replace(/[MZ]/g, '')
    .split(/[L ]/)
    .filter(Boolean)
    .sort()
}

describe('prism', () => {
  it('lifts the ground parallelogram by the height', () => {
    const k = prism([10, 50], [4, 0], [2, -3], 7)
    expect(k).toEqual({ g0: [10, 50], gu: [14, 50], gv: [12, 47], guv: [16, 47], t0: [10, 43], tu: [14, 43], tv: [12, 40], tuv: [16, 40] })
  })
})

describe('isoCube', () => {
  it('stands on the centre of its ground diamond, 2:1 by default', () => {
    expect(isoCube({ x: 28, y: 34, size: 16, height: 24, tone: 'accent' })).toEqual({
      top: '28,2 44,10 28,18 12,10',
      left: '12,10 28,18 28,42 12,34',
      right: '28,18 44,10 44,34 28,42',
      tone: 'accent',
    })
  })

  it('is the same cube as the verdict block and the icons', () => {
    const cube = isoCube({ x: 28, y: 34, size: 16, height: 24 })
    const block = verdictBlock('pass')
    expect(vertexSet(cube.top)).toEqual(vertexSet(block.top))
    expect(vertexSet(cube.left)).toEqual(vertexSet(block.front))
    expect(vertexSet(cube.right)).toEqual(vertexSet(block.side))
    const exec = isoBox({ x: 32, y: 54, width: 20, depth: 20, height: 24 })
    expect(vertexSet(isoCube({ x: 32, y: 44, size: 20, height: 24 }).top)).toEqual(vertexSet(exec.top))
  })

  it('draws the true isometric of the S mark', () => {
    // One cube of design/brand/s-mark.svg: edge 40, ground centre (38.64, 244).
    const p = isoCubePoints({ x: 38.64, y: 244, size: 40 * 0.866, height: 40, ratio: ISO_TRUE })
    const fmt = (pts: Point[]) => pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
    expect(fmt(p.left)).toBe('4.0,204.0 38.6,224.0 38.6,264.0 4.0,244.0')
    expect(fmt(p.right)).toBe('38.6,224.0 73.3,204.0 73.3,244.0 38.6,264.0')
    expect(fmt(p.top)).toBe('38.6,184.0 73.3,204.0 38.6,224.0 4.0,204.0')
  })

  it('draws a flat tile at height 0', () => {
    const c = isoCube({ x: 0, y: 0, size: 4, height: 0 })
    expect(c.left).toBe('-4,0 0,2 0,2 -4,0')
    expect(c.top).toBe('0,-2 4,0 0,2 -4,0')
  })

  it('keeps the oblique projection on the same core', () => {
    const k = prism([20, 160], [12, 0], [5.6, -4.55], 30)
    expect(obliqueBox({ x: 20, y: 160, width: 12, height: 30, dx: 5.6, dy: 4.55 }).top).toBe(
      `M${k.t0.join(',')}L${k.tu.join(',')}L${k.tuv.map((v) => Math.round(v * 100) / 100).join(',')}L${k.tv.map((v) => Math.round(v * 100) / 100).join(',')}Z`,
    )
  })
})
