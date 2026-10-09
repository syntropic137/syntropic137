// @vitest-environment jsdom
// Iso City
import '../../components/_test/setup'
import { render } from '@testing-library/svelte'
import { describe, expect, it } from 'vitest'
import { ISO_CITY_EXAMPLES } from './examples'
import IsoCity from './IsoCity.svelte'

describe('Iso City', () => {
  const hero = ISO_CITY_EXAMPLES[0]!.props
  it('draws one block per day with motion classes only when asked', () => {
    const { container } = render(IsoCity, { ...hero, animate: false, drift: false })
    expect(container.querySelectorAll('g[data-tone]')).toHaveLength(26 * 11)
    expect(container.querySelector('.sky-rise, .sky-drift')).toBeNull()
  })
  it('rises, pulses live days and flashes failed days, finitely, via motion.css', () => {
    const { container } = render(IsoCity, { ...hero })
    expect(container.querySelector('.sky-drift')).not.toBeNull()
    expect(container.querySelectorAll('g.sky-pulse')).toHaveLength(4)
    expect(container.querySelectorAll('g.sky-flash')).toHaveLength(2)
    expect(container.querySelectorAll('g[data-tone="errored"]')).toHaveLength(1)
    const live = container.querySelector<SVGGElement>('g.sky-pulse')!
    expect(live.style.animationDelay).toMatch(/^[\d.]+s, [\d.]+s$/)
  })
})
