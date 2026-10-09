import { describe, expect, it } from 'vitest'
import { OUTCOME_RANGES, outcomeRangeNoun, outcomeRangeStart, parseOutcomeRange } from './outcomeRange'

describe('outcome range (feedback 9587ce0c)', () => {
  const now = Date.parse('2026-10-09T12:00:00Z')
  it('offers All first, then 24h, 7d, 30d', () => {
    expect(OUTCOME_RANGES.map((r) => r.value)).toEqual(['all', '24h', '7d', '30d'])
  })
  it('parses stored values, defaulting to All', () => {
    expect(parseOutcomeRange('7d')).toBe('7d')
    expect(parseOutcomeRange('1h')).toBe('all')
    expect(parseOutcomeRange(null)).toBe('all')
  })
  it('bounds started_after with an offset', () => {
    expect(outcomeRangeStart('all', now)).toBeUndefined()
    expect(outcomeRangeStart('24h', now)).toBe('2026-10-08T12:00:00.000Z')
    expect(outcomeRangeStart('7d', now)).toBe('2026-10-02T12:00:00.000Z')
    expect(outcomeRangeStart('30d', now)).toBe('2026-09-09T12:00:00.000Z')
  })
  it('names the range in the heading', () => {
    expect(outcomeRangeNoun('all')).toBe('executions')
    expect(outcomeRangeNoun('30d')).toBe('in 30d')
  })
})
