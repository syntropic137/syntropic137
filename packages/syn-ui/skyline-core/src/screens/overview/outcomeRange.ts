/**
 * Outcomes card range (feedback 9587ce0c): All (default), 24h, 7d, 30d.
 * `/metrics` takes no time window, so a ranged view counts `/executions`
 * with `started_after` (its `status_counts`); All keeps the metrics totals.
 */

export type OutcomeRange = 'all' | '24h' | '7d' | '30d'

export const OUTCOME_RANGES: readonly { value: OutcomeRange; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
]

export const DEFAULT_OUTCOME_RANGE: OutcomeRange = 'all'

/** localStorage key for the viewer's chosen range (a per-viewer convenience). */
export const OUTCOME_RANGE_STORAGE_KEY = 'syn-ui:overview:outcome-range'

const DAY_MS = 86_400_000
const RANGE_MS: Record<Exclude<OutcomeRange, 'all'>, number> = { '24h': DAY_MS, '7d': 7 * DAY_MS, '30d': 30 * DAY_MS }

/** A stored or chosen value back to a range; anything unknown is the default. */
export function parseOutcomeRange(value: string | null | undefined): OutcomeRange {
  return OUTCOME_RANGES.some((r) => r.value === value) ? (value as OutcomeRange) : DEFAULT_OUTCOME_RANGE
}

/** `started_after` for the range, ISO 8601 with an offset; undefined for All. */
export function outcomeRangeStart(range: OutcomeRange, now: number): string | undefined {
  return range === 'all' ? undefined : new Date(now - RANGE_MS[range]).toISOString()
}

/** The ring's noun: "executions", or "in 7d" for a ranged view ("Outcomes · 601 in 7d"). */
export function outcomeRangeNoun(range: OutcomeRange): string {
  return range === 'all' ? 'executions' : `in ${range}`
}
