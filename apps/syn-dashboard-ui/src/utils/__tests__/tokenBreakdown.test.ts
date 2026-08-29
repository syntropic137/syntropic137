import { describe, expect, it } from 'vitest'

import { formatTokenBreakdown } from '../formatters'

/**
 * The heatmap's token sublabel read "697.0K in / 57.8K out" beneath a headline
 * of 9.9M, so it looked like a breakdown that had lost 9.1M tokens. It had not:
 * cache tokens are 92% of the volume and the sublabel simply omitted them.
 *
 * Numbers below are the real all-time totals from the dev stack.
 */
describe('formatTokenBreakdown', () => {
  it('accounts for cache tokens so the parts visibly reach the headline', () => {
    const label = formatTokenBreakdown({
      inputTokens: 696977,
      outputTokens: 57754,
      cacheCreationTokens: 986683,
      cacheReadTokens: 8118441,
    })

    expect(label).toBe('697.0K in / 57.8K out / 9.1M cached')
  })

  it('omits the cached segment when nothing was cached', () => {
    const label = formatTokenBreakdown({
      inputTokens: 1200,
      outputTokens: 340,
      cacheCreationTokens: 0,
      cacheReadTokens: 0,
    })

    expect(label).toBe('1.2K in / 340 out')
  })
})
