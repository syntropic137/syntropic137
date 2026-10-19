import { request } from '../client'
import type { components } from '../generated/api-types'
import { cached } from '../keys'

export type ContributionHeatmap = components['schemas']['ContributionHeatmapResponse']
export type HeatmapDay = components['schemas']['HeatmapDayBucketResponse']

/**
 * Per-day breakdown keys the API sends in `HeatmapDay.breakdown`
 * (sessions, executions, commits, cost_usd, tokens, the four token buckets
 * and failed). The failed count is also a top-level field, `HeatmapDay.failed`:
 * executions that ended failed on that UTC day.
 */
export type HeatmapBreakdownKey =
  | 'sessions'
  | 'executions'
  | 'commits'
  | 'cost_usd'
  | 'tokens'
  | 'input_tokens'
  | 'output_tokens'
  | 'cache_creation_tokens'
  | 'cache_read_tokens'
  /** Executions that ended failed that day; the same value as `HeatmapDay.failed`. */
  | 'failed'

export interface HeatmapParams {
  organization_id?: string
  system_id?: string
  repo_id?: string
  /** ISO date, inclusive. */
  start_date?: string
  end_date?: string
  /** Which count drives `count` (default "sessions"). */
  metric?: string
}

/** The Overview Skyline's data: one bucket per day with its full breakdown. */
export function getContributionHeatmap(params: HeatmapParams = {}, signal?: AbortSignal): Promise<ContributionHeatmap> {
  const query = { metric: 'sessions', ...params }
  return cached('getContributionHeatmap', [query], (s) => request('/insights/contribution-heatmap', { query, signal: s }), { signal, staleAfter: 'list' })
}
