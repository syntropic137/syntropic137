import { describe, expect, it } from 'vitest'
import { extrudeColors, isoBox, obliqueBox, obliqueFloor, polygonPath, polygonPoints, scaleLinear, sqrtHeight } from './index'

describe('paths', () => {
  it('builds closed paths with rounded coordinates', () => {
    expect(polygonPath([[0, 0], [10.123, 0], [10, 5.555]])).toBe('M0,0L10.12,0L10,5.56Z')
    expect(polygonPath([])).toBe('')
    expect(polygonPoints([[1, 2], [3, 4]])).toBe('1,2 3,4')
  })
})

describe('extrudeColors', () => {
  it('derives faces from the accent by default', () => {
    expect(extrudeColors()).toEqual({
      front: 'var(--ds-color-accent)',
      top: 'color-mix(in oklab, var(--ds-color-accent) 58%, var(--ds-color-fg))',
      side: 'color-mix(in oklab, var(--ds-color-accent) 50%, var(--ds-color-bg))',
    })
  })
  it('takes any base and mix', () => {
    const f = extrudeColors('var(--sky-color-data-2)', { topMix: 70 })
    expect(f.front).toBe('var(--sky-color-data-2)')
    expect(f.top).toContain('70%')
    expect(JSON.stringify(f)).not.toMatch(/#[0-9a-f]{3,8}/i)
  })
})

describe('obliqueBox', () => {
  it('matches the Skyline bar recipe from the Overview board', () => {
    const b = obliqueBox({ x: 20, y: 160, width: 12, height: 30, dx: 5.6, dy: 4.55 })
    expect(b.front).toBe('M20,160L32,160L32,130L20,130Z')
    expect(b.side).toBe('M32,160L37.6,155.45L37.6,125.45L32,130Z')
    expect(b.top).toBe('M20,130L32,130L37.6,125.45L25.6,125.45Z')
  })
  it('draws only the floor tile at height 0', () => {
    const b = obliqueBox({ x: 0, y: 10, width: 12, height: 0, dx: 5, dy: 4 })
    expect(b.front).toBe('')
    expect(b.side).toBe('')
    expect(obliqueFloor({ x: 0, y: 10, width: 12, dx: 5, dy: 4 })).toBe('M0,10L12,10L17,6L5,6Z')
  })
})

describe('isoBox', () => {
  it('reproduces the Execution object icon', () => {
    const b = isoBox({ x: 32, y: 54, width: 20, depth: 20, height: 24 })
    expect(b.top).toBe('M32,30L52,20L32,10L12,20Z')
    expect(b.front).toBe('M12,20L32,30L32,54L12,44Z')
    expect(b.side).toBe('M32,30L52,20L52,44L32,54Z')
  })
})

describe('scales', () => {
  it('maps linearly and clamps', () => {
    const s = scaleLinear([0, 10], [0, 100])
    expect(s(5)).toBe(50)
    expect(s(20)).toBe(200)
    expect(scaleLinear([0, 10], [0, 100], true)(20)).toBe(100)
    expect(scaleLinear([5, 5], [0, 100])(5)).toBe(0)
  })
  it('scales heights by square root with a floor', () => {
    expect(sqrtHeight(0, 43, 90, 12)).toBe(0)
    expect(sqrtHeight(43, 43, 90, 12)).toBe(90)
    expect(sqrtHeight(1, 43, 90, 12)).toBe(14)
    expect(sqrtHeight(1, 1000, 90, 12)).toBe(12)
  })
})
