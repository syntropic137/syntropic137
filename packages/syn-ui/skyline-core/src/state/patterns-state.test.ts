import { describe, expect, it } from 'vitest'
import { dayStepper, gridCursor, gridKey, initialDayStepper, run, stepperKey, stepperPosition } from './index'

describe('dayStepper', () => {
  it('starts on the latest day and wraps both ways', () => {
    const s = initialDayStepper(11)
    expect(s).toEqual({ index: 10, count: 11 })
    expect(stepperPosition(s)).toBe('11 of 11 active days')
    expect(run(dayStepper, s, [{ type: 'next' }]).index).toBe(0)
    expect(run(dayStepper, s, [{ type: 'prev' }, { type: 'prev' }]).index).toBe(8)
    expect(run(dayStepper, s, [{ type: 'first' }]).index).toBe(0)
    expect(run(dayStepper, { index: 3, count: 11 }, [{ type: 'last' }]).index).toBe(10)
  })
  it('picks a bar and ignores out-of-range picks', () => {
    const s = initialDayStepper(5)
    expect(dayStepper(s, { type: 'pick', index: 2 }).index).toBe(2)
    expect(dayStepper(s, { type: 'pick', index: 9 })).toBe(s)
    expect(dayStepper(s, { type: 'pick', index: 4 })).toBe(s)
  })
  it('survives data changes', () => {
    const s = { index: 2, count: 5 }
    expect(dayStepper(s, { type: 'resize', count: 3, keep: 2 })).toEqual({ index: 2, count: 3 })
    expect(dayStepper(s, { type: 'resize', count: 2, keep: 2 })).toEqual({ index: 1, count: 2 })
    const empty = dayStepper(s, { type: 'resize', count: 0 })
    expect(empty).toEqual({ index: null, count: 0 })
    expect(dayStepper(empty, { type: 'next' })).toBe(empty)
    expect(stepperPosition(empty)).toBe('No active days')
    expect(stepperPosition({ index: 0, count: 1 })).toBe('1 of 1 active day')
  })
  it('maps keys', () => {
    expect(stepperKey('ArrowLeft')).toEqual({ type: 'prev' })
    expect(stepperKey('ArrowRight')).toEqual({ type: 'next' })
    expect(stepperKey('End')).toEqual({ type: 'last' })
    expect(stepperKey('a')).toBeNull()
  })
})

describe('gridCursor', () => {
  const s = { row: 0, col: 3, rows: 6, cols: 4 }
  it('moves without wrapping', () => {
    expect(gridCursor(s, gridKey('ArrowRight')!)).toBe(s)
    expect(gridCursor(s, gridKey('ArrowDown')!)).toMatchObject({ row: 1, col: 3 })
    expect(gridCursor(s, gridKey('ArrowLeft')!)).toMatchObject({ row: 0, col: 2 })
    expect(gridCursor(s, gridKey('ArrowUp')!)).toBe(s)
  })
  it('jumps with Home and End', () => {
    expect(gridCursor(s, gridKey('Home')!)).toMatchObject({ row: 0, col: 0 })
    expect(gridCursor({ ...s, col: 0 }, gridKey('End', true)!)).toMatchObject({ row: 5, col: 3 })
    expect(gridKey('x')).toBeNull()
  })
  it('picks and clamps on resize', () => {
    expect(gridCursor(s, { type: 'pick', row: 4, col: 1 })).toMatchObject({ row: 4, col: 1 })
    expect(gridCursor({ ...s, row: 5 }, { type: 'resize', rows: 3, cols: 2 })).toEqual({ row: 2, col: 1, rows: 3, cols: 2 })
  })
})
