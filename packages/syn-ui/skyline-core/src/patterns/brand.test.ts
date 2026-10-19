import { describe, expect, it } from 'vitest'
import { cityDelay, sMarkDelay, S_MARK_FACES } from '../geometry'

describe('landing motion stagger and S faces', () => {
  it('matches the board delays', () => {
    expect(sMarkDelay(0)).toBe(0.25)
    expect(sMarkDelay(10)).toBe(1.15)
    expect(cityDelay(0)).toBe(0.15)
    expect(cityDelay(20)).toBe(0.85)
  })

  it('fills the S from tokens only', () => {
    for (const f of Object.values(S_MARK_FACES)) {
      for (const v of [f.left, f.right, f.top, f.stroke ?? '']) expect(v).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|\bwhite\b|\bblack\b/i)
    }
  })
})
