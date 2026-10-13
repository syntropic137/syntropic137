// @vitest-environment jsdom
// S Mark
import '../../components/_test/setup'
import { render, screen } from '@testing-library/svelte'
import { describe, expect, it } from 'vitest'
import SMark from './SMark.svelte'

describe('S Mark', () => {
  it('draws eleven cubes, static unless animated', () => {
    const { container } = render(SMark, { size: 26 })
    const svg = screen.getByRole('img', { name: 'Syntropic137' })
    expect(svg.style.width).toBe('26px')
    expect(container.querySelectorAll('g')).toHaveLength(11)
    expect(container.querySelector('.sky-sdrop')).toBeNull()
  })
  it('staggers the cube drop and can be decorative', () => {
    const { container } = render(SMark, { animate: true, label: '', size: '15%' })
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('aria-hidden')).toBe('true')
    expect(svg.style.width).toBe('15%')
    const cubes = [...container.querySelectorAll<SVGGElement>('g.sky-sdrop')]
    expect(cubes).toHaveLength(11)
    expect(cubes[0]!.style.animationDelay).toBe('0.25s')
    expect(cubes[10]!.style.animationDelay).toBe('1.15s')
  })
})
