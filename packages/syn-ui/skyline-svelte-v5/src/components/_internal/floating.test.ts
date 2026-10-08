import { describe, expect, it } from 'vitest'
import { placeFloating } from './floating'

const viewport = { width: 390, height: 800 }
const floating = { width: 200, height: 120 }

describe('placeFloating', () => {
  it('places below and centred by default', () => {
    const p = placeFloating({ anchor: { x: 100, y: 100, width: 100, height: 40 }, floating, viewport })
    expect(p).toMatchObject({ side: 'bottom', x: 50, y: 148 })
  })
  it('aligns start and end', () => {
    const anchor = { x: 100, y: 100, width: 100, height: 40 }
    expect(placeFloating({ anchor, floating, viewport, align: 'start' }).x).toBe(100)
    expect(placeFloating({ anchor, floating, viewport, align: 'end' }).x).toBe(8)
  })
  it('flips to the top when there is no room below', () => {
    const p = placeFloating({ anchor: { x: 100, y: 740, width: 100, height: 40 }, floating, viewport })
    expect(p.side).toBe('top')
    expect(p.y).toBe(740 - 8 - 120)
  })
  it('keeps the preferred side when the other side is worse', () => {
    const p = placeFloating({ anchor: { x: 100, y: 60, width: 100, height: 700 }, floating, viewport, side: 'top' })
    expect(p.side).toBe('top')
    const q = placeFloating({ anchor: { x: 100, y: 100, width: 100, height: 650 }, floating, viewport, side: 'top' })
    expect(q.side).toBe('top')
  })
  it('clamps into the viewport at phone width', () => {
    const p = placeFloating({ anchor: { x: 340, y: 100, width: 40, height: 40 }, floating, viewport })
    expect(p.x).toBe(390 - 8 - 200)
    const wide = placeFloating({ anchor: { x: 0, y: 100, width: 40, height: 40 }, floating: { width: 500, height: 50 }, viewport })
    expect(wide.x).toBe(8)
  })
  it('places on the sides', () => {
    const p = placeFloating({ anchor: { x: 10, y: 100, width: 40, height: 40 }, floating, viewport, side: 'right' })
    expect(p).toMatchObject({ side: 'right', x: 58 })
    const flipped = placeFloating({ anchor: { x: 10, y: 100, width: 40, height: 40 }, floating, viewport, side: 'left' })
    expect(flipped.side).toBe('right')
  })
  it('reports the room available on the chosen side', () => {
    const p = placeFloating({ anchor: { x: 100, y: 100, width: 100, height: 40 }, floating, viewport })
    expect(p.available).toBe(800 - 140 - 8 - 8)
  })
})
