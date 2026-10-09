import { request } from '../client'
import type { components } from '../generated/api-types'
import { cached } from '../keys'

export type ContributionHeatmap = components['schemas']['ContributionHeatmapResponse']
export type HeatmapDay = components['schemas']['HeatmapDayBucketResponse']

/**
 * Per-day breakdown keys the API sends in `HeatmapDay.breakdown`
 * (sessions, executions, commits, cost_usd, tokens and the four token buckets).
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

export type EventList = components['schemas']['EventListResponse']
export type RecentEvent = components['schemas']['EventResponse']

export interface RecentEventsParams {
  /** Max events to return (the API default is 50). */
  limit?: number
  /** Only this event type, for example `git_commit`. */
  event_type?: string
}

/** GET /events/recent: the global activity feed, newest first (the Overview's Live commits seed). */
export function listRecentEvents(params: RecentEventsParams = {}, signal?: AbortSignal): Promise<EventList> {
  return cached('listRecentEvents', [params], (s) => request('/events/recent', { query: { ...params }, signal: s }), { signal, staleAfter: 'list' })
}
