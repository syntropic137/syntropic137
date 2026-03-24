import { useCallback, useEffect, useState } from 'react'

import { getMetrics, listWorkflows } from '../api/client'
import type { MetricsResponse, WorkflowSummary } from '../types'

/** Polling interval for dashboard refresh (10 seconds) */
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
