import { describe, expect, it } from 'vitest'

import { executionTokenTotals } from '../executionTokens'

/**
 * `executionTokenTotals` reconciles a live total against parts that lag it.
 * Its one load-bearing promise is that the parts it reports add up to the
 * total it reports, so nothing on screen can show a headline its own
 * breakdown cannot account for (the shape of #873).
 *
 * The component tests cover the case that matters in production — Lane 2
 * ahead of Lane 1. These cover the whole input domain, including the reversed
 * case those tests never reach.
 */

function fields(
  total: number,
  input: number,
  output: number,
  cacheCreation: number,
  cacheRead: number,
) {
  return {
    total_tokens: total,
    total_input_tokens: input,
    total_output_tokens: output,
    total_cache_creation_tokens: cacheCreation,
    total_cache_read_tokens: cacheRead,
  }
}

describe('executionTokenTotals', () => {
  const cases = [
    { name: 'live total, nothing attributed yet (a phase mid-run)', args: fields(1000, 0, 0, 0, 0) },
    { name: 'live total ahead of a partial breakdown', args: fields(1000, 100, 200, 0, 0) },
    { name: 'breakdown exactly accounts for the total', args: fields(1000, 100, 200, 300, 400) },
    // total_tokens is max(lane2, lane1sum) at the API, so this should not
    // reach the UI - but a stale or partial payload must not render a
    // negative row or a headline smaller than its own parts.
    { name: 'parts ahead of the total (stale or partial payload)', args: fields(50, 100, 200, 300, 400) },
    { name: 'no tokens at all', args: fields(0, 0, 0, 0, 0) },
  ]

  it.each(cases)('parts add up to the total: $name', ({ args }) => {
    const t = executionTokenTotals(args)
    const sum =
      t.inputTokens + t.outputTokens + t.cacheCreationTokens + t.cacheReadTokens + t.inProgressTokens

    expect(sum).toBe(t.total)
    expect(t.inProgressTokens).toBeGreaterThanOrEqual(0)
    expect(t.total).toBeGreaterThanOrEqual(0)
  })

  it('reports the live total rather than the sum of the frozen parts', () => {
    // The value under test could not arise from the component fields.
    expect(executionTokenTotals(fields(1234567, 0, 0, 0, 0)).total).toBe(1234567)
    expect(executionTokenTotals(fields(1234567, 0, 0, 0, 0)).inProgressTokens).toBe(1234567)
  })

  it('never reports a remainder when the breakdown is already complete', () => {
    expect(executionTokenTotals(fields(1000, 100, 200, 300, 400)).inProgressTokens).toBe(0)
  })

  it('falls back to the parts when they exceed the reported total', () => {
    const t = executionTokenTotals(fields(50, 100, 200, 300, 400))

    expect(t.total).toBe(1000)
    expect(t.inProgressTokens).toBe(0)
  })
})
