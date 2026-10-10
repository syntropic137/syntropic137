// @vitest-environment jsdom
// Hero City
import '../../components/_test/setup'
import { render } from '@testing-library/svelte'
import { describe, expect, it } from 'vitest'
import { HERO_CITY_EXAMPLES } from './examples'
import HeroCity from './HeroCity.svelte'

describe('Hero City', () => {
  const hero = HERO_CITY_EXAMPLES[0]!.props
  it('draws one block per day with motion classes only when asked', () => {
    const { container } = render(HeroCity, { ...hero, animate: false, drift: false })
    expect(container.querySelectorAll('g[data-tone]')).toHaveLength(26 * 11)
    expect(container.querySelector('.sky-rise, .sky-drift')).toBeNull()
  })
  it('rises, pulses live days and flashes failed days, finitely, via motion.css', () => {
    const { container } = render(HeroCity, { ...hero })
    expect(container.querySelector('.sky-drift')).not.toBeNull()
    expect(container.querySelectorAll('g.sky-pulse')).toHaveLength(4)
    expect(container.querySelectorAll('g.sky-flash')).toHaveLength(2)
    expect(container.querySelectorAll('g[data-tone="errored"]')).toHaveLength(1)
    const live = container.querySelector<SVGGElement>('g.sky-pulse')!
    expect(live.style.animationDelay).toMatch(/^[\d.]+s, [\d.]+s$/)
  })
  it('fades quiet blocks by default and keeps them opaque when solid', () => {
    const glass = render(HeroCity, { ...hero, animate: false })
    const faded = [...glass.container.querySelectorAll<SVGGElement>('g[data-tone]')].filter((g) => g.style.opacity !== '')
    expect(faded.length).toBeGreaterThan(0)
    const solid = render(HeroCity, { ...hero, animate: false, fill: 'solid' })
    const groups = [...solid.container.querySelectorAll<SVGGElement>('g[data-tone]')]
    expect(groups.every((g) => g.style.opacity === '')).toBe(true)
  })
})
