/**
 * Cache rate badges come from the API, never from a multiplier baked in here.
 *
 * The card used to hard-code "0.1x" / "1.25x", which is wrong for Opus 5.5
 * (cache reads bill at 0.05x) and meaningless for a scope mixing models. The
 * server now words the rate for the scope, or sends null when no single rate
 * is true; null means no badge. Token counts are exec-105b88d56234 (beta.7).
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TokenBreakdown } from '../TokenBreakdown'

const LIVE = {
  inputTokens: 22828,
  outputTokens: 5163,
  cacheCreationTokens: 33928,
  cacheReadTokens: 294495,
}

describe('TokenBreakdown cache rate badges', () => {
  it('renders the rate labels the API sends, verbatim', () => {
    render(
      <TokenBreakdown {...LIVE} cacheReadRateDisplay="0.05x rate" cacheWriteRateDisplay="1.25x rate" />,
    )
    expect(screen.getByText('0.05x rate')).toBeTruthy()
    expect(screen.getByText('1.25x rate')).toBeTruthy()
  })

  it('renders no badge when the API says no single rate applies', () => {
    const { container } = render(
      <TokenBreakdown {...LIVE} cacheReadRateDisplay={null} cacheWriteRateDisplay={null} />,
    )
    expect(container.textContent).not.toMatch(/x rate/)
    expect(screen.getByText('Cache Read')).toBeTruthy()
  })

  it('renders no badge when the server predates the field', () => {
    const { container } = render(<TokenBreakdown {...LIVE} />)
    expect(container.textContent).not.toMatch(/x rate/)
  })
})
