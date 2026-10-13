import { describe, expect, it } from 'vitest'
import { dragWeeks, glideFocusFirst, initialIsoGlide, isoGlide, ISO_GLIDE_BUFFER, type IsoGlideEvent, type IsoGlideState } from './index'

const run = (events: IsoGlideEvent[], from: IsoGlideState = initialIsoGlide) => events.reduce(isoGlide, from)
const at38 = run([{ type: 'target', first: 38, reduced: false }])

describe('isoGlide (owner, Oct 10: fluid scroll)', () => {
  it('lands on the first target without moving', () => {
    expect(at38).toEqual({ anchor: 38, shift: 0, gliding: false, dragging: false, pad: ISO_GLIDE_BUFFER, dragFrom: 0 })
  })

  it('keeps the previous window laid out while it glides, and moves it only on landing', () => {
    const g = isoGlide(at38, { type: 'target', first: 34, reduced: false })
    expect(g).toMatchObject({ anchor: 38, shift: 4, gliding: true })
    expect(g.pad).toBeGreaterThanOrEqual(4 + ISO_GLIDE_BUFFER)
    expect(isoGlide(g, { type: 'land', first: 34 })).toEqual({ anchor: 34, shift: 0, gliding: false, dragging: false, pad: ISO_GLIDE_BUFFER, dragFrom: 0 })
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
    expect(isoGlide(at38, { type: 'target', first: 34, reduced: true })).toEqual({ anchor: 34, shift: 0, gliding: false, dragging: false, pad: ISO_GLIDE_BUFFER, dragFrom: 0 })
  })

  it('drags from where it is, then glides to the target or back', () => {
    const d = run([{ type: 'drag', weeks: 1.5, first: 38 }, { type: 'drag', weeks: 3.2, first: 38 }], at38)
    expect(d).toMatchObject({ anchor: 38, shift: 3.2, dragging: true, gliding: false })
    expect(glideFocusFirst(d, 38)).toBe(35)
    const back = isoGlide(d, { type: 'release', first: 38, reduced: false })
    expect(back).toMatchObject({ anchor: 38, shift: 0, dragging: false, gliding: true })
    expect(isoGlide(back, { type: 'target', first: 34, reduced: false })).toMatchObject({ anchor: 38, shift: 4, gliding: true })
  })

  it('ignores targets mid-drag and focuses the target otherwise', () => {
    const d = isoGlide(at38, { type: 'drag', weeks: 2, first: 38 })
    expect(isoGlide(d, { type: 'target', first: 30, reduced: false })).toBe(d)
    expect(glideFocusFirst(at38, 34)).toBe(34)
  })
})

describe('isoGlide drag and release (codex review 2 of #1856)', () => {
  it('a drag that starts mid-glide keeps the anchor and starts from the displayed shift', () => {
    const gliding = isoGlide(at38, { type: 'target', first: 34, reduced: false }) // heading for shift 4
    // The transition is 60% of the way there when the finger lands.
    const d = isoGlide(gliding, { type: 'drag', weeks: 0.2, first: 34, from: 2.4 })
    expect(d).toMatchObject({ anchor: 38, dragging: true, gliding: false, dragFrom: 2.4 })
    expect(d.shift).toBeCloseTo(2.6, 5)
    expect(dragWeeks(d)).toBeCloseTo(0.2, 5)
    const more = isoGlide(d, { type: 'drag', weeks: 1, first: 34 })
    expect(more.anchor).toBe(38)
    expect(more.shift).toBeCloseTo(3.4, 5)
  })

  it('releases toward the current window from wherever the drag is', () => {
    const d = run([{ type: 'target', first: 34, reduced: false }, { type: 'drag', weeks: 0.5, first: 34, from: 2 }], at38)
    expect(isoGlide(d, { type: 'release', first: 34, reduced: false })).toMatchObject({ anchor: 38, shift: 4, gliding: true, dragging: false })
  })

  it('reduced motion: a release lands at once, with no glide back', () => {
    const d = isoGlide(at38, { type: 'drag', weeks: 0.4, first: 38 })
    expect(isoGlide(d, { type: 'release', first: 38, reduced: true })).toEqual({ anchor: 38, shift: 0, gliding: false, dragging: false, pad: ISO_GLIDE_BUFFER, dragFrom: 0 })
  })
})
