/**
 * The dashboard homepage: totals, and the workflows that run most.
 *
 * The totals move for two different reasons, so they are kept current two ways.
 * An execution starting or finishing is a discrete fact the server already
 * publishes, so it arrives over SSE and the totals update immediately instead
 * of up to ten seconds later. Tokens and cost, by contrast, accumulate
 * continuously while an agent works, and there is no event for "a total went
 * up" - so those still need a poll, and this is the one surface in the
 * dashboard where polling is the only option rather than the lazy one.
 *
 * That poll used to be `setInterval(refreshMetrics, 10000)` with nothing
 * checking whether the last request had come back (#1095). It now goes through
 * `useSerialRefresh`, so ten seconds is a floor rather than a period: if
 * `/metrics` is taking eighteen seconds, the next poll is eighteen seconds
 * after the last one landed, not stacked on top of it.
 */

import { useCallback, useEffect, useState } from 'react'

import { getMetrics, listWorkflows } from '../api/client'
import type { MetricsResponse, WorkflowSummary } from '../types'
import { useLiveRefresh } from './useLiveRefresh'
import { useSerialRefresh } from './useSerialRefresh'

/** Shortest gap between polls of `/metrics`; the real gap tracks its latency. */
const METRICS_POLL_INTERVAL_MS = 10000

/** Execution lifecycle - the totals that jump rather than creep. */
const METRICS_LIVE_EVENTS: ReadonlySet<string> = new Set([
  'WorkflowExecutionStarted',
  'WorkflowCompleted',
  'WorkflowFailed',
])

/** How many workflows the "most active" panel shows. */
const RECENT_WORKFLOW_COUNT = 5

export interface UseDashboardDataResult {
  metrics: MetricsResponse | null
  recentWorkflows: WorkflowSummary[]
  loading: boolean
  isConnected: boolean
}

export function useDashboardData(): UseDashboardDataResult {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null)
  const [recentWorkflows, setRecentWorkflows] = useState<WorkflowSummary[]>([])
  const [loading, setLoading] = useState(true)

  const isConnected = !loading

  const fetchMetrics = useCallback(
    (signal: AbortSignal): Promise<void> =>
      getMetrics(undefined, signal)
        .then((next) => {
          if (!signal.aborted) setMetrics(next)
        })
        .catch((error) => {
          if (!signal.aborted) console.error(error)
        })
        .finally(() => {
          if (!signal.aborted) setLoading(false)
        }),
    [],
  )

  const { refetch } = useSerialRefresh({
    fetch: fetchMetrics,
    pollIntervalMs: METRICS_POLL_INTERVAL_MS,
  })

  useLiveRefresh({ onChanged: refetch, liveEvents: METRICS_LIVE_EVENTS })

  useEffect(() => {
    refetch()
  }, [refetch])

  // The most-run workflows are a masthead, not a live number: fetched once.
  useEffect(() => {
    listWorkflows({ page_size: RECENT_WORKFLOW_COUNT, order_by: '-runs_count' })
      .then((data) => setRecentWorkflows(data.workflows))
      .catch(console.error)
  }, [])

  return { metrics, recentWorkflows, loading, isConnected }
}
