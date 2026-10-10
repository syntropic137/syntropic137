import { describe, expect, it } from 'vitest'
import { axisTicks, linearFit, linePath, niceCeil, sparkPath, spreadEndLabels, timeX, valueY } from './trend'

describe('trend geometry', () => {
  it('maps time onto a padded 2..98 axis and centres a zero span', () => {
    expect(timeX(0, 0, 10)).toBe(2)
    expect(timeX(10, 0, 10)).toBe(98)
    expect(timeX(5, 0, 10)).toBe(50)
    expect(timeX(20, 0, 10)).toBe(98)
    expect(timeX(3, 3, 3)).toBe(50)
  })

  it('picks the first nice step at or above the value, then multiples of the last', () => {
    const steps = [0.4, 0.8, 1.2, 1.6]
    expect(niceCeil(1.28, steps)).toBe(1.6)
    expect(niceCeil(0.4, steps)).toBe(0.4)
    expect(niceCeil(0, steps)).toBe(0.4)
    expect(niceCeil(4, steps)).toBeCloseTo(4.8)
    expect(niceCeil(7, [])).toBe(7)
  })

  it('scales values onto 0..100 and clamps', () => {
    expect(valueY(0.8, 1.6)).toBe(50)
    expect(valueY(3, 1.6)).toBe(100)
    expect(valueY(-1, 1.6)).toBe(0)
    expect(valueY(1, 0)).toBe(0)
    axisTicks(1.6).forEach((v, k) => expect(v).toBeCloseTo(k * 0.4))
  })

  it('draws a path in viewBox units with y flipped', () => {
    expect(linePath([{ x: 0, y: 0 }, { x: 50, y: 100 }, { x: 100, y: 70 }], 1000, 200)).toBe('M0 200 L500 0 L1000 60')
    expect(linePath([], 1000, 200)).toBe('')
  })

  it('spreads crowded end labels apart and keeps them inside the box', () => {
    const out = spreadEndLabels([
      { key: 'a', top: 95 },
      { key: 'b', top: 96 },
      { key: 'c', top: 10 },
    ])
    expect(out.map((l) => l.key)).toEqual(['c', 'a', 'b'])
    expect(out[2]!.top).toBeCloseTo(100)
    expect(out[2]!.top - out[1]!.top).toBeCloseTo(11)
    expect(out[0]!.top).toBeCloseTo(4)
  })

  it('fits a least-squares line', () => {
    expect(linearFit([10, 20, 30]).start).toBeCloseTo(10)
    expect(linearFit([10, 20, 30]).end).toBeCloseTo(30)
    expect(linearFit([5])).toEqual({ start: 5, end: 5 })
    expect(linearFit([])).toEqual({ start: 0, end: 0 })
    const f = linearFit([10, 30, 10, 30])
    expect(f.end - f.start).toBeCloseTo(12)
  })

  it('draws a sparkline between its own min and max, flat when too short', () => {
    expect(sparkPath([1, 2, 3])).toBe('M0 36 L100 20 L200 4')
    expect(sparkPath([5, 5])).toBe('M0 20 L200 20')
    expect(sparkPath([])).toBe('M0 38 L200 38')
  })
})
