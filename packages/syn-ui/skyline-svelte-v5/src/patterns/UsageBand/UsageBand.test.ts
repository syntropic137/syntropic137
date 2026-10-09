// @vitest-environment jsdom
// Usage Band
import '../../components/_test/setup'
import { render, screen } from '@testing-library/svelte'
import { describe, expect, it } from 'vitest'
import UsageBand from './UsageBand.svelte'

describe('Usage Band', () => {
  const tokens = { cacheRead: 582_400, cacheWrite: 201_600, output: 235_200, input: 100_800 }
  it('draws the extruded band with the full legend by default', () => {
    const { container } = render(UsageBand, { tokens })
    expect(container.querySelector('svg[part="band"]')).not.toBeNull()
    expect(screen.getByRole('img').getAttribute('aria-label')).toBe('Tokens by type: Cache read 52.0 percent, Cache write 18.0 percent, Output 21.0 percent, Input 9.0 percent')
    expect(screen.getByText('582,400')).toBeTruthy()
  })
  it('draws the landing flat bar with a compact legend', () => {
    const { container } = render(UsageBand, { tokens, shape: 'flat', legend: 'compact' })
    expect(container.querySelectorAll('.sky-usage-band__flat > span')).toHaveLength(4)
    expect(screen.queryByText('582,400')).toBeNull()
    expect(screen.getByText('Cache write')).toBeTruthy()
  })
  it('says when nothing was recorded', () => {
    render(UsageBand, { tokens: { cacheRead: 0, cacheWrite: 0, output: 0, input: 0 } })
    expect(screen.getByText('No tokens recorded.')).toBeTruthy()
  })
})
