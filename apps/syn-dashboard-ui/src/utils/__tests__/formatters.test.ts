import { describe, expect, it } from 'vitest'
import {
  formatCost,
  formatDate,
  formatDuration,
  formatDurationFromRange,
  formatDurationSeconds,
  formatRelativeTime,
  formatTime,
  formatTimestampLocale,
  formatTokens,
} from '../formatters'

describe('formatCost', () => {
  it('uses 6 decimal places for values < $0.01', () => {
    expect(formatCost(0.001234)).toBe('$0.001234')
    expect(formatCost(0.000001)).toBe('$0.000001')
  })

  it('uses 4 decimal places for values < $1.00', () => {
    expect(formatCost(0.0123)).toBe('$0.0123')
    expect(formatCost(0.5)).toBe('$0.5000')
  })

  it('uses 2 decimal places for values >= $1.00', () => {
    expect(formatCost(1.0)).toBe('$1.00')
    expect(formatCost(99.999)).toBe('$100.00')
  })

  it('handles zero', () => {
    expect(formatCost(0)).toBe('$0.000000')
  })
})

describe('formatDuration', () => {
  it('formats milliseconds', () => {
    expect(formatDuration(500)).toBe('500ms')
    expect(formatDuration(0)).toBe('0ms')
  })

  it('formats seconds', () => {
    expect(formatDuration(1000)).toBe('1.0s')
    expect(formatDuration(30000)).toBe('30.0s')
  })

  it('formats minutes', () => {
    expect(formatDuration(60000)).toBe('1.0m')
    expect(formatDuration(150000)).toBe('2.5m')
  })

  it('formats hours', () => {
    expect(formatDuration(3600000)).toBe('1.0h')
    expect(formatDuration(7200000)).toBe('2.0h')
  })
})

describe('formatTokens', () => {
  it('formats raw count for small values', () => {
    expect(formatTokens(0)).toBe('0')
    expect(formatTokens(999)).toBe('999')
  })

  it('formats K suffix for thousands', () => {
    expect(formatTokens(1000)).toBe('1.0K')
    expect(formatTokens(15500)).toBe('15.5K')
  })

  it('formats M suffix for millions', () => {
    expect(formatTokens(1000000)).toBe('1.0M')
    expect(formatTokens(2500000)).toBe('2.5M')
  })
})

describe('formatTime', () => {
  it('formats ISO timestamp to time string', () => {
    const result = formatTime('2026-03-23T14:30:00Z')
    // Output varies by locale, just check it returns a non-empty string
    expect(result.length).toBeGreaterThan(0)
  })
})

describe('formatDate', () => {
  it('formats ISO date string', () => {
    const result = formatDate('2026-03-23T14:30:00Z')
    expect(result.length).toBeGreaterThan(0)
    expect(result).not.toBe('—')
  })

  it('returns dash for null/undefined', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate(undefined)).toBe('—')
  })
})

describe('formatDurationSeconds', () => {
  it('formats seconds', () => {
    expect(formatDurationSeconds(30)).toBe('30s')
    expect(formatDurationSeconds(0)).toBe('0s')
  })

  it('formats minutes and seconds', () => {
    expect(formatDurationSeconds(90)).toBe('1m 30s')
    expect(formatDurationSeconds(120)).toBe('2m')
  })

  it('formats hours and minutes', () => {
    expect(formatDurationSeconds(3660)).toBe('1h 1m')
    expect(formatDurationSeconds(3600)).toBe('1h')
  })

  it('returns dash for null/undefined/negative', () => {
    expect(formatDurationSeconds(null)).toBe('—')
    expect(formatDurationSeconds(undefined)).toBe('—')
    expect(formatDurationSeconds(-1)).toBe('—')
  })
})

describe('formatDurationFromRange', () => {
  it('calculates duration between timestamps', () => {
    const result = formatDurationFromRange(
      '2026-03-23T14:00:00Z',
      '2026-03-23T14:01:30Z',
    )
    expect(result).toBe('1m 30s')
  })

  it('uses now for ongoing duration', () => {
    const start = '2026-03-23T14:00:00Z'
    const now = new Date('2026-03-23T14:00:45Z').getTime()
    expect(formatDurationFromRange(start, null, now)).toBe('45s')
  })

  it('returns dash when startedAt is null', () => {
    expect(formatDurationFromRange(null, null)).toBe('—')
  })
})

describe('formatRelativeTime', () => {
  const now = new Date('2026-04-19T12:00:00Z').getTime()

  it('returns "just now" for very recent timestamps', () => {
    expect(formatRelativeTime('2026-04-19T11:59:58Z', now)).toBe('just now')
  })

  it('formats seconds in the past', () => {
    expect(formatRelativeTime('2026-04-19T11:59:30Z', now)).toBe('30s ago')
  })

  it('formats minutes in the past', () => {
    expect(formatRelativeTime('2026-04-19T11:56:00Z', now)).toBe('4m ago')
  })

  it('formats hours in the past', () => {
    expect(formatRelativeTime('2026-04-19T09:00:00Z', now)).toBe('3h ago')
  })

  it('formats days in the past', () => {
    expect(formatRelativeTime('2026-04-17T12:00:00Z', now)).toBe('2d ago')
  })

  it('formats future timestamps with "in"', () => {
    expect(formatRelativeTime('2026-04-19T12:02:00Z', now)).toBe('in 2m')
  })

  it('returns dash for null/invalid input', () => {
    expect(formatRelativeTime(null)).toBe('—')
    expect(formatRelativeTime(undefined)).toBe('—')
    expect(formatRelativeTime('not-a-date')).toBe('—')
  })
})

describe('formatTimestampLocale', () => {
  it('produces a non-empty locale string for a valid ISO timestamp', () => {
    const result = formatTimestampLocale('2026-04-19T12:00:00Z')
    expect(result.length).toBeGreaterThan(0)
    expect(result).not.toBe('—')
  })

  it('returns dash for null/undefined/invalid', () => {
    expect(formatTimestampLocale(null)).toBe('—')
    expect(formatTimestampLocale(undefined)).toBe('—')
    expect(formatTimestampLocale('not-a-date')).toBe('—')
  })
})
