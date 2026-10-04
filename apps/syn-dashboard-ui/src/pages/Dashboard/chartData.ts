import type { ExecutionStatusCounts, MetricsResponse } from '../../types'

export interface ChartDataItem {
  [key: string]: unknown
  name: string
  value: number
  fill: string
}

/*
 * The four disjoint token buckets the API reports, so the segments add up to
 * `total_tokens`. Input and output alone showed about 1% of the volume once
 * cache reads dominated. Categorical dark-mode slots, validated on the card
 * surface.
 */
export function tokenSegments(metrics: MetricsResponse): ChartDataItem[] {
  return [
    { name: 'Input', value: metrics.total_input_tokens, fill: '#3987e5' },
    { name: 'Output', value: metrics.total_output_tokens, fill: '#d95926' },
    { name: 'Cache read', value: metrics.total_cache_read_tokens, fill: '#199e70' },
    { name: 'Cache creation', value: metrics.total_cache_creation_tokens, fill: '#c98500' },
  ]
}

/*
 * One entry per domain status, in slice order. Hues follow StatusBadge
 * (green completed, amber cancelled, red failed, orange interrupted), ordered
 * so the two warm near-neighbours never touch; the legend names every slice.
 */
const STATUS_SLICES: { status: keyof ExecutionStatusCounts; name: string; fill: string }[] = [
  { status: 'completed', name: 'Completed', fill: '#16a34a' },
  { status: 'cancelled', name: 'Cancelled', fill: '#d97706' },
  { status: 'running', name: 'Running', fill: '#2563eb' },
  { status: 'failed', name: 'Failed', fill: '#dc2626' },
  { status: 'not_started', name: 'Not started', fill: '#94a3b8' },
  { status: 'interrupted', name: 'Interrupted', fill: '#ea580c' },
]

/** One slice per status that has any executions. */
export function statusSlices(counts: ExecutionStatusCounts): ChartDataItem[] {
  return STATUS_SLICES
    .map(({ status, name, fill }) => ({ name, value: counts[status], fill }))
    .filter((d) => d.value > 0)
}
