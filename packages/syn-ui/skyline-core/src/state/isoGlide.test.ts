import { describe, expect, it } from 'vitest'
import { glideFocusFirst, initialIsoGlide, isoGlide, ISO_GLIDE_BUFFER, type IsoGlideEvent, type IsoGlideState } from './index'

const run = (events: IsoGlideEvent[], from: IsoGlideState = initialIsoGlide) => events.reduce(isoGlide, from)
const at38 = run([{ type: 'target', first: 38, reduced: false }])

describe('isoGlide (owner, Oct 10: fluid scroll)', () => {
  it('lands on the first target without moving', () => {
    expect(at38).toEqual({ anchor: 38, shift: 0, gliding: false, dragging: false, pad: ISO_GLIDE_BUFFER })
  })

  it('keeps the previous window laid out while it glides, and moves it only on landing', () => {
    const g = isoGlide(at38, { type: 'target', first: 34, reduced: false })
    expect(g).toMatchObject({ anchor: 38, shift: 4, gliding: true })
    expect(g.pad).toBeGreaterThanOrEqual(4 + ISO_GLIDE_BUFFER)
    expect(isoGlide(g, { type: 'land', first: 34 })).toEqual({ anchor: 34, shift: 0, gliding: false, dragging: false, pad: ISO_GLIDE_BUFFER })
  })

  it('retargets a glide in progress without resetting it (no jump back)', () => {
    const one = isoGlide(at38, { type: 'target', first: 34, reduced: false })
    const two = isoGlide(one, { type: 'target', first: 30, reduced: false })
    expect(two.anchor).toBe(38)
    expect(two.shift).toBe(8)
    expect(two.gliding).toBe(true)
    // Coming back the other way still glides from the same anchor.
    expect(isoGlide(two, { type: 'target', first: 38, reduced: false })).toMatchObject({ anchor: 38, shift: 0, gliding: true })
  })

  it('lands at once under reduced motion (the component crossfades)', () => {
    expect(isoGlide(at38, { type: 'target', first: 34, reduced: true })).toEqual({ anchor: 34, shift: 0, gliding: false, dragging: false, pad: ISO_GLIDE_BUFFER })
  })

  it('drags from where it is, then glides to the target or back', () => {
    const d = run([{ type: 'drag', weeks: 1.5, first: 38 }, { type: 'drag', weeks: 3.2, first: 38 }], at38)
    expect(d).toMatchObject({ anchor: 38, shift: 3.2, dragging: true, gliding: false })
    expect(glideFocusFirst(d, 38)).toBe(35)
    const back = isoGlide(d, { type: 'release' })
    expect(back).toMatchObject({ anchor: 38, shift: 0, dragging: false, gliding: true })
    expect(isoGlide(back, { type: 'target', first: 34, reduced: false })).toMatchObject({ anchor: 38, shift: 4, gliding: true })
  })

  it('ignores targets mid-drag and focuses the target otherwise', () => {
    const d = isoGlide(at38, { type: 'drag', weeks: 2, first: 38 })
    expect(isoGlide(d, { type: 'target', first: 30, reduced: false })).toBe(d)
    expect(glideFocusFirst(at38, 34)).toBe(34)
  })
})
