import { useCallback, useEffect, useState } from 'react'

import { getMetrics, listWorkflows } from '../api/client'
import type { MetricsResponse, WorkflowSummary } from '../types'

/**
 * Polling interval for dashboard refresh (10 seconds).
 *
 * This one stays a poll, deliberately (#1095). `/sse/activity` broadcasts
 * exactly five event types — WorkflowExecutionStarted, WorkflowCompleted,
 * WorkflowFailed, SessionStarted, SessionCompleted — which covers the counts
 * on this page and none of the totals. `total_tokens`, `total_cost_usd` and
 * `total_artifacts` move on `OperationRecorded` and `ArtifactCreated`, and
 * those are published per-execution only. Carrying them globally would mean a
 * frame per tool call across every concurrent run delivered to every open
 * dashboard, which is a firehose, not a fix.
 *
 * Subscribing for half the fields would not let the poll go, so the poll is
 * still what keeps this page current. What is missing to remove it is a
 * server-side aggregate — metrics recomputed on the API and pushed as one
 * frame — not a wider event feed.
 */
const POLL_INTERVAL = 10000

export interface UseDashboardDataResult {
  metrics: MetricsResponse | null
  recentWorkflows: WorkflowSummary[]
  loading: boolean
  isConnected: boolean
}

/**
 * Encapsulates dashboard data fetching with polling for live updates.
 */
export function useDashboardData(): UseDashboardDataResult {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null)
  const [recentWorkflows, setRecentWorkflows] = useState<WorkflowSummary[]>([])
  const [loading, setLoading] = useState(true)

  const isConnected = !loading

  const refreshMetrics = useCallback(() => {
    getMetrics()
      .then((metricsData) => setMetrics(metricsData))
      .catch(console.error)
  }, [])

  // Initial data fetch
  useEffect(() => {
    Promise.all([
      getMetrics(),
      listWorkflows({ page_size: 5, order_by: '-runs_count' }),
    ])
      .then(([metricsData, workflowsData]) => {
        setMetrics(metricsData)
        setRecentWorkflows(workflowsData.workflows)
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  // Polling for live updates
  useEffect(() => {
    const interval = setInterval(refreshMetrics, POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [refreshMetrics])

  return { metrics, recentWorkflows, loading, isConnected }
}
