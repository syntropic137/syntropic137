import { useCallback, useEffect, useState } from 'react'
import { listAllExecutions } from '../api/executions'
import type { ExecutionListItem } from '../types'
import { useLiveTimer } from './useLiveTimer'
import { usePolling } from './usePolling'

const POLL_INTERVAL_RUNNING = 5000
const POLL_INTERVAL_IDLE = 30000
const PAGE_SIZE = 50

export interface UseExecutionListResult {
  executions: ExecutionListItem[]
  loading: boolean
  error: string | null
  statusFilter: string
  setStatusFilter: (status: string) => void
  page: number
  setPage: React.Dispatch<React.SetStateAction<number>>
  pageSize: number
  hasRunning: boolean
  now: number
}

export function useExecutionList(): UseExecutionListResult {
  const [executions, setExecutions] = useState<ExecutionListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [page, setPage] = useState(1)

  const hasRunning = executions.some((e) => e.status === 'running')
  const now = useLiveTimer(hasRunning)

  const refreshExecutions = useCallback(() => {
    listAllExecutions({
      status: statusFilter || undefined,
      page,
      page_size: PAGE_SIZE,
    })
      .then((response) => {
        setExecutions(response.executions)
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }, [statusFilter, page])

  // Initial data fetch
  useEffect(() => {
    refreshExecutions()
  }, [refreshExecutions])

  // Polling for live updates (faster when executions are running)
  usePolling(
    refreshExecutions,
    hasRunning ? POLL_INTERVAL_RUNNING : POLL_INTERVAL_IDLE,
    true,
  )

  return {
    executions,
    loading,
    error,
    statusFilter,
    setStatusFilter,
    page,
    setPage,
    pageSize: PAGE_SIZE,
    hasRunning,
    now,
  }
}
