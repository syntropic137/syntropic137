/**
 * What agents shipped in a window, against the window before:
 * GET /metrics/shipped?days=14 (7 | 14 | 30; optional workflow_id). The
 * Overview's "Shipped by agents" block reads it.
 *
 * TODO(#624): hand-written to the response model of PR
 * "feat/metrics-shipped-by-agents" until it reaches this package's generated
 * api-types.ts; then alias components['schemas'] here.
 */
import { request } from '../client'
import { cached } from '../keys'

export type ShippedDays = 7 | 14 | 30

export interface ShippedPoint {
  /** ISO date (UTC day). */
  date: string
  value: number
}

/** One tile. `merge_rate` values are percentages, 0 to 100. */
export interface ShippedMetric {
  total: number | null
  previous_total: number | null
  delta: number | null
  /** "+38%", "+5 pts", "+3": render verbatim. */
  delta_display: string | null
  /** One point per day, oldest first. */
  series: ShippedPoint[]
  /** Why the server cannot answer this tile, when total is null. */
  reason?: string | null
}

export interface ShippedWorkflow {
  workflow_id: string
  name: string
  commits: number
  prs_merged: number
}

export interface ShippedMetricsResponse {
  window: { days: number; from: string; to: string }
  previous: { from: string; to: string }
  /** Null when the server cannot answer the tile; `reason` says why. */
  commits: ShippedMetric | null
  prs_opened: ShippedMetric | null
  prs_merged: ShippedMetric | null
  merge_rate: ShippedMetric | null
  repos_touched: ShippedMetric | null
  /** Per-tile reasons for null tiles. */
  reasons?: Partial<Record<'commits' | 'prs_opened' | 'prs_merged' | 'merge_rate' | 'repos_touched', string>> | null
  /** Full names, "owner/repo". */
  repos: string[]
  by_workflow: ShippedWorkflow[]
}

export interface ShippedParams {
  days?: ShippedDays
  workflow_id?: string
}

export function getShippedMetrics(params: ShippedParams = {}, signal?: AbortSignal): Promise<ShippedMetricsResponse> {
  const query = { days: params.days ?? 14, ...(params.workflow_id ? { workflow_id: params.workflow_id } : {}) }
  return cached('getShippedMetrics', [query], (s) => request('/metrics/shipped', { query, signal: s }), { signal, staleAfter: 'metrics' })
}
