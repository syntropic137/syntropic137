/**
 * Execution list data + live updates.
 *
 * Mirrors useSessionList: URL-backed status + time window filters, sortable
 * columns, SSE-driven live patches via the shared activity stream
 * (WorkflowExecutionStarted / WorkflowCompleted / WorkflowFailed), polling
 * fallback when SSE is disconnected, and refetch-while-running so Lane 2
 * numbers (tokens, cost, duration) tick without manual refresh.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { listAllExecutions } from '../api/executions'
import { useResetView } from './useResetView'
import type { ExecutionListItem, SSEEventFrame, TimeWindow } from '../types'
import { sortExecutions } from '../utils/executionSort'
import { useActivityStream } from './useActivityStream'
import { timeWindowToStartedAfter, useFilterUrlState } from './useFilterUrlState'
import { useRefetchWhileRunning } from './useRefetchWhileRunning'
import {
  useSortUrlState,
  type SortConfig,
  type SortState,
} from './useSortUrlState'
import { useStatusCounts } from './useStatusCounts'
import { useThrottledRefetch } from './useThrottledRefetch'

const REFETCH_THROTTLE_MS = 500
const POLL_INTERVAL_MS = 5000
const PAGE_SIZE = 50
const EXECUTION_LIVE_EVENTS = new Set([
  'WorkflowExecutionStarted',
  'WorkflowCompleted',
  'WorkflowFailed',
])
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

export type ExecutionSortKey =
  | 'status'
  | 'workflow'
  | 'progress'
  | 'tokens'
  | 'cost'
  | 'duration'
  | 'repos'
  | 'started'

const EXECUTION_SORT_CONFIG: SortConfig<ExecutionSortKey> = {
  validKeys: ['status', 'workflow', 'progress', 'tokens', 'cost', 'duration', 'repos', 'started'],
  defaultKey: 'started',
  defaultDir: 'desc',
}

function isTerminalExecution(e: ExecutionListItem): boolean {
  return TERMINAL_STATUSES.has(e.status)
}

function matchesQuery(e: ExecutionListItem, query: string): boolean {
  const q = query.toLowerCase()
  return (
    e.workflow_execution_id.toLowerCase().includes(q) ||
    e.workflow_id.toLowerCase().includes(q) ||
    (e.workflow_name?.toLowerCase().includes(q) ?? false)
  )
}

function applyClientFilters(
  rows: ExecutionListItem[],
  selectedStatuses: Set<string>,
  timeWindow: TimeWindow,
  searchQuery: string,
): ExecutionListItem[] {
  let out = rows
  if (selectedStatuses.size > 1) {
    out = out.filter((e) => selectedStatuses.has(e.status))
  }
  const startedAfter = timeWindowToStartedAfter(timeWindow)
  if (startedAfter) {
    out = out.filter((e) => e.started_at !== null && e.started_at >= startedAfter)
  }
  if (searchQuery) out = out.filter((e) => matchesQuery(e, searchQuery))
  return out
}

export interface UseExecutionListResult {
  executions: ExecutionListItem[]
  filteredExecutions: ExecutionListItem[]
  loading: boolean
  searchQuery: string
  setSearchQuery: (query: string) => void
  selectedStatuses: Set<string>
  toggleStatus: (status: string) => void
  clearStatuses: () => void
  timeWindow: TimeWindow
  setTimeWindow: (next: TimeWindow) => void
  /** Restore default filters AND default sort. */
  resetView: () => void
  /** True when filters and sort are at their defaults. */
  isDefaultView: boolean
  statusCounts: Record<string, number>
  sort: SortState<ExecutionSortKey>
  toggleSort: (key: ExecutionSortKey) => void
  connected: boolean
  lastEventAt: number | null
}

export function useExecutionList(): UseExecutionListResult {
  const {
    selectedStatuses,
    timeWindow,
    toggleStatus,
    setTimeWindow,
    clearStatuses,
  } = useFilterUrlState()
  const { sort, toggleSort, isDefault: isDefaultSort } = useSortUrlState(EXECUTION_SORT_CONFIG)
  const isDefaultView = isDefaultSort && selectedStatuses.size === 0 && timeWindow === '24h'
  const resetView = useResetView()

  const [executions, setExecutions] = useState<ExecutionListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')

  const statusesKey = useMemo(
    () => Array.from(selectedStatuses).sort().join(','),
    [selectedStatuses],
  )

  const fetchNow = useCallback(() => {
    // The list endpoint accepts a single status (legacy); when multiple are
    // selected we fall back to client-side narrowing via filteredExecutions.
    const singleStatus =
      statusesKey && !statusesKey.includes(',') ? statusesKey : undefined
    listAllExecutions({
      status: singleStatus,
      page: 1,
      page_size: PAGE_SIZE,
    })
      .then((response) => setExecutions(response.executions))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [statusesKey])

  const scheduleRefetch = useThrottledRefetch(fetchNow, REFETCH_THROTTLE_MS)

  useEffect(() => {
    fetchNow()
  }, [fetchNow])

  const handleFrame = useCallback(
    (frame: SSEEventFrame) => {
      if (frame.type === 'event' && EXECUTION_LIVE_EVENTS.has(frame.event_type)) {
        scheduleRefetch()
      }
    },
    [scheduleRefetch],
  )

  const { connected, lastEventAt } = useActivityStream({
    onEvent: handleFrame,
    filter: (eventType) => EXECUTION_LIVE_EVENTS.has(eventType),
  })

  useEffect(() => {
    if (connected) return
    const id = setInterval(fetchNow, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [connected, fetchNow])

  useRefetchWhileRunning({
    items: executions,
    isTerminal: isTerminalExecution,
    refetch: fetchNow,
  })

  const filteredExecutions = useMemo(() => {
    const rows = applyClientFilters(executions, selectedStatuses, timeWindow, searchQuery)
    return sortExecutions(rows, sort.key, sort.dir)
  }, [executions, selectedStatuses, timeWindow, searchQuery, sort.key, sort.dir])

  const statusCounts = useStatusCounts(executions)

  return {
    executions,
    filteredExecutions,
    loading,
    searchQuery,
    setSearchQuery,
    selectedStatuses,
    toggleStatus,
    clearStatuses,
    timeWindow,
    setTimeWindow,
    resetView,
    isDefaultView,
    statusCounts,
    sort,
    toggleSort,
    connected,
    lastEventAt,
  }
}
