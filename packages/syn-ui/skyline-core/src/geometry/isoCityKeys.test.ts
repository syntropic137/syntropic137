import { describe, expect, it } from 'vitest'
import { isoCityKeyIntent, isoCityRovingDate } from './index'

const chart = { onDay: false, offset: 2, maxOffset: 9 }
const day = { ...chart, onDay: true }

describe('isoCityKeyIntent (codex review of #1856: keyboard intent out of the component)', () => {
  it('steps active days with the arrows on a day', () => {
    expect(isoCityKeyIntent('ArrowLeft', day)).toEqual({ kind: 'step', dir: -1 })
    expect(isoCityKeyIntent('ArrowRight', day)).toEqual({ kind: 'step', dir: 1 })
  })
  it('scrolls a month with the arrows on the chart and with Page Up/Down anywhere', () => {
    expect(isoCityKeyIntent('ArrowLeft', chart)).toEqual({ kind: 'offset', offset: 3 })
    expect(isoCityKeyIntent('ArrowRight', chart)).toEqual({ kind: 'offset', offset: 1 })
    expect(isoCityKeyIntent('PageUp', day)).toEqual({ kind: 'offset', offset: 3 })
    expect(isoCityKeyIntent('PageDown', day)).toEqual({ kind: 'offset', offset: 1 })
  })
  it('clamps to the history and jumps with Home and End', () => {
    expect(isoCityKeyIntent('ArrowLeft', { ...chart, offset: 9 })).toEqual({ kind: 'offset', offset: 9 })
    expect(isoCityKeyIntent('ArrowRight', { ...chart, offset: 0 })).toEqual({ kind: 'offset', offset: 0 })
    expect(isoCityKeyIntent('Home', chart)).toEqual({ kind: 'offset', offset: 9 })
    expect(isoCityKeyIntent('End', day)).toEqual({ kind: 'offset', offset: 0 })
  })
  it('leaves every other key alone', () => {
    for (const k of ['Enter', ' ', 'Tab', 'ArrowUp', 'ArrowDown', 'a']) expect(isoCityKeyIntent(k, day)).toBeNull()
  })
})

describe('isoCityRovingDate (codex review of #1856: keyboard entry after scrolling)', () => {
  const visible = ['2026-05-04', '2026-05-12', '2026-06-30']
  it('keeps the selected day when it is in view', () => {
    expect(isoCityRovingDate(visible, '2026-05-12')).toBe('2026-05-12')
  })
  it('falls back to the visible day nearest the selection once it scrolls out of view', () => {
    expect(isoCityRovingDate(visible, '2026-10-05')).toBe('2026-06-30')
    expect(isoCityRovingDate(visible, '2026-01-01')).toBe('2026-05-04')
  })
  it('uses the newest visible day with no selection, and null with nothing in view', () => {
    expect(isoCityRovingDate(visible, null)).toBe('2026-06-30')
    expect(isoCityRovingDate([], '2026-05-12')).toBeNull()
  })
})
