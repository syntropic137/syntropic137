import { describe, expect, it } from 'vitest'
import {
  MINUS,
  formatSigned,
  formatSignedCost,
  formatSignedPoints,
  pointsPerDollar,
  pointsPerDollarValue,
  UNKNOWN,
  dayKey,
  durationBetween,
  formatBytes,
  formatClock,
  formatCost,
  formatCostPrecise,
  formatCostWithCoverage,
  formatDate,
  formatDateTime,
  formatDuration,
  formatDurationPrecise,
  formatDurationSeconds,
  formatInteger,
  formatPercent,
  formatRelativeTime,
  formatTokenBreakdown,
  formatTokens,
  shortId,
  toNumber,
  toTime,
  totalTokens,
} from './index'

describe('shared parsing', () => {
  it('reads numbers and decimal strings, rejects junk', () => {
    expect(toNumber(3)).toBe(3)
    expect(toNumber('0.2162')).toBe(0.2162)
    expect(toNumber('')).toBeNull()
    expect(toNumber('abc')).toBeNull()
    expect(toNumber(Number.NaN)).toBeNull()
    expect(toNumber(null)).toBeNull()
  })
  it('reads times from ISO, ms and Date', () => {
    expect(toTime('2026-10-07T00:00:00Z')).toBe(Date.UTC(2026, 9, 7))
    expect(toTime(5)).toBe(5)
    expect(toTime(new Date(7))).toBe(7)
    expect(toTime('garbage')).toBeNull()
    expect(toTime(undefined)).toBeNull()
  })
})

describe('formatTokens', () => {
  it('matches the canvas samples', () => {
    expect(formatTokens(950)).toBe('950')
    expect(formatTokens(261_734)).toBe('261.7k')
    expect(formatTokens(396_791)).toBe('396.8k')
    expect(formatTokens(2_790_000)).toBe('2.79M')
    expect(formatTokens(10_260_000)).toBe('10.26M')
  })
  it('rolls a rounded tier up instead of printing 1000.0k', () => {
    expect(formatTokens(999_949)).toBe('999.9k')
    expect(formatTokens(999_960)).toBe('1.00M')
    expect(formatTokens(999_996_000)).toBe('1.00B')
  })
  it('supports upper case and custom digits', () => {
    expect(formatTokens(176_000, { case: 'upper' })).toBe('176.0K')
    expect(formatTokens(9_300_000, { digits: { m: 1 } })).toBe('9.3M')
  })
  it('handles unknowns and strings', () => {
    expect(formatTokens(null)).toBe(UNKNOWN)
    expect(formatTokens(-1)).toBe(UNKNOWN)
    expect(formatTokens('1500')).toBe('1.5k')
    expect(formatTokens(0)).toBe('0')
  })
  it('condenses at each tier boundary (feedback 418d59db)', () => {
    expect(formatTokens(999)).toBe('999')
    expect(formatTokens(1_000)).toBe('1.0k')
    expect(formatTokens(999_999)).toBe('1.00M')
    expect(formatTokens(1_000_000)).toBe('1.00M')
    expect(formatTokens(19_824_689)).toBe('19.82M')
    expect(formatTokens(999_999_999)).toBe('1.00B')
    expect(formatTokens(1e9)).toBe('1.00B')
    expect(formatTokens(14_540_000_000)).toBe('14.54B')
  })
  it('breaks tokens down and totals them', () => {
    const b = { input: 12_100, output: 3_400, cacheWrite: 40_000, cacheRead: 200_000 }
    expect(totalTokens(b)).toBe(255_500)
    expect(formatTokenBreakdown(b)).toBe('12.1k in / 3.4k out / 240.0k cached')
    expect(formatTokenBreakdown({ ...b, cacheWrite: 0, cacheRead: 0 })).toBe('12.1k in / 3.4k out')
  })
})

describe('formatCost', () => {
  it('formats compact USD', () => {
    expect(formatCost(0.33)).toBe('$0.33')
    expect(formatCost('0.2162')).toBe('$0.22')
    expect(formatCost(1204.5)).toBe('$1,204.50')
    expect(formatCost(0)).toBe('$0.00')
    expect(formatCost(0.004)).toBe('<$0.01')
    expect(formatCost(-1)).toBe(UNKNOWN)
    expect(formatCost('x')).toBe(UNKNOWN)
  })
  it('formats precise USD like the React app', () => {
    expect(formatCostPrecise(0.0798)).toBe('$0.0798')
    expect(formatCostPrecise(0.000123)).toBe('$0.000123')
    expect(formatCostPrecise(2.5)).toBe('$2.50')
  })
  it('flags incomplete costs', () => {
    expect(formatCostWithCoverage(0.21, 0)).toBe('$0.21')
    expect(formatCostWithCoverage(0, 3)).toBe('unpriced')
    expect(formatCostWithCoverage(0.21, 2)).toBe('≥$0.21 (partial)')
    expect(formatCostWithCoverage('nope', 0)).toBe('unknown')
  })
})

describe('durations', () => {
  it('formats whole units', () => {
    expect(formatDuration(0)).toBe('0s')
    expect(formatDuration(8_000)).toBe('8s')
    expect(formatDuration(227_000)).toBe('3m 47s')
    expect(formatDuration(240_000)).toBe('4m')
    expect(formatDuration(3_840_000)).toBe('1h 4m')
    expect(formatDuration(7_200_000)).toBe('2h')
    expect(formatDuration(183_600_000)).toBe('2d 3h')
    expect(formatDuration(-5)).toBe(UNKNOWN)
    expect(formatDuration(Number.NaN)).toBe(UNKNOWN)
  })
  it('formats seconds and precise durations', () => {
    expect(formatDurationSeconds(62)).toBe('1m 2s')
    expect(formatDurationSeconds(null)).toBe(UNKNOWN)
    expect(formatDurationPrecise(340)).toBe('340ms')
    expect(formatDurationPrecise(24_300)).toBe('24.3s')
    expect(formatDurationPrecise(80_600)).toBe('1m 21s')
  })
  it('measures ranges, open ends use now', () => {
    expect(durationBetween('2026-10-07T00:00:00Z', '2026-10-07T00:03:47Z')).toBe(227_000)
    expect(durationBetween('2026-10-07T00:00:00Z', null, Date.UTC(2026, 9, 7, 0, 0, 5))).toBe(5_000)
    expect(durationBetween(null, null)).toBeNull()
    expect(durationBetween('2026-10-07T00:00:05Z', '2026-10-07T00:00:00Z')).toBeNull()
  })
})

describe('time', () => {
  const now = Date.UTC(2026, 9, 7, 12, 0, 0)
  it('formats relative times', () => {
    expect(formatRelativeTime(now - 10_000, { now })).toBe('just now')
    expect(formatRelativeTime(now - 5 * 60_000, { now })).toBe('5m ago')
    expect(formatRelativeTime(now - 60 * 60_000, { now })).toBe('1h ago')
    expect(formatRelativeTime(now - 5 * 86_400_000, { now })).toBe('5d ago')
    expect(formatRelativeTime(now - 15 * 86_400_000, { now })).toBe('2w ago')
    expect(formatRelativeTime(now + 5 * 60_000, { now })).toBe('in 5m')
    expect(formatRelativeTime('2026-08-01T00:00:00Z', { now, timeZone: 'UTC' })).toBe('Aug 1')
    expect(formatRelativeTime('2025-09-12T00:00:00Z', { now, timeZone: 'UTC' })).toBe('Sep 12, 2025')
    expect(formatRelativeTime(null)).toBe(UNKNOWN)
  })
  it('formats absolute dates and clocks', () => {
    expect(formatDate('2026-09-12T10:00:00Z', { now, timeZone: 'UTC' })).toBe('Sep 12')
    expect(formatDateTime('2026-09-12T14:05:00Z', { timeZone: 'UTC' })).toBe('Sep 12, 14:05')
    expect(formatClock('2026-09-12T14:05:09Z', { timeZone: 'UTC' })).toBe('14:05:09')
    expect(dayKey('2026-10-07T23:30:00Z')).toBe('2026-10-07')
    expect(dayKey('2026-10-07T23:30:00Z', 'Asia/Tokyo')).toBe('2026-10-08')
    expect(dayKey('bad')).toBeNull()
  })
})

describe('bytes and numbers', () => {
  it('formats bytes like the canvas', () => {
    expect(formatBytes(211)).toBe('211 B')
    expect(formatBytes(2_970)).toBe('2.9 KB')
    expect(formatBytes(20_275)).toBe('19.8 KB')
    expect(formatBytes(1_572_864)).toBe('1.5 MB')
    expect(formatBytes(1_048_575)).toBe('1.0 MB')
    expect(formatBytes(null)).toBe(UNKNOWN)
  })
  it('formats integers, percents and IDs', () => {
    expect(formatInteger(396_791)).toBe('396,791')
    expect(formatInteger('12')).toBe('12')
    expect(formatPercent(0.4217)).toBe('42%')
    expect(formatPercent(0.4217, 1)).toBe('42.2%')
    expect(shortId('exec-66e14f235942')).toBe('66e14f23')
    expect(shortId('2fd5ec12-aaaa')).toBe('2fd5ec12')
    expect(shortId(null)).toBe(UNKNOWN)
  })
})

describe('signed deltas and quality per dollar', () => {
  it('signs with a real minus and ± at zero', () => {
    expect(formatSignedPoints(24)).toBe('+24 pts')
    expect(formatSignedPoints(-10)).toBe('−10 pts')
    expect(formatSignedPoints(0)).toBe('±0 pts')
    expect(formatSignedPoints(null)).toBe('—')
    expect(formatSignedCost(-0.11)).toBe('−$0.11')
    expect(formatSignedCost(0.17333)).toBe('+$0.17')
    expect(formatSigned(-3, String)).toBe('−3')
    expect(MINUS).toBe('−')
  })
  it('ranks quality per dollar', () => {
    expect(pointsPerDollar(87, 0.5166666)).toBe('168 pts/$')
    expect(pointsPerDollar(91, '1.04')).toBe('88 pts/$')
    expect(pointsPerDollar(91, 0)).toBe('—')
    expect(pointsPerDollarValue(75, 0.6)).toBe(125)
    expect(pointsPerDollarValue(75, null)).toBeNull()
  })
})
