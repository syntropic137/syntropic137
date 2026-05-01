/**
 * Session list data + live updates.
 *
 * Owns all data concerns for the SessionList page:
 *   - URL-backed filter state (status chips + time window)
 *   - initial fetch (and refetch when filters change)
 *   - live patches via the shared activity stream (SessionStarted/Completed)
 *   - polling fallback gated on the stream being disconnected
 *
 * Pages should call this hook and feed the result to presentational
 * components — no fetching, formatting, or SSE handling lives in the page.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listSessions } from '../api/sessions'
import type { SSEEventFrame, SessionSummary, TimeWindow } from '../types'
import { sortSessions } from '../utils/sessionSort'
import { useActivityStream } from './useActivityStream'
import { timeWindowToStartedAfter, useFilterUrlState } from './useFilterUrlState'
import { useRefetchWhileRunning } from './useRefetchWhileRunning'
import {
  useSortUrlState,
  type SortConfig,
  type SortKey,
  type SortState,
} from './useSortUrlState'

const SESSION_SORT_CONFIG: SortConfig<SortKey> = {
  validKeys: [
    'status',
    'workflow',
    'phase',
    'repos',
    'tokens',
    'cost',
    'duration',
    'started',
  ],
  defaultKey: 'started',
  defaultDir: 'desc',
}
import { useStatusCounts } from './useStatusCounts'
import { useThrottledRefetch } from './useThrottledRefetch'

const REFETCH_THROTTLE_MS = 500
const POLL_INTERVAL_MS = 5000
const SESSION_LIVE_EVENTS = new Set(['SessionStarted', 'SessionCompleted'])
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

function isTerminalSession(s: SessionSummary): boolean {
  return TERMINAL_STATUSES.has(s.status)
}

export interface UseSessionListResult {
  sessions: SessionSummary[]
  filteredSessions: SessionSummary[]
  loading: boolean
  searchQuery: string
  setSearchQuery: (query: string) => void
  selectedStatuses: Set<string>
  toggleStatus: (status: string) => void
  clearStatuses: () => void
  timeWindow: TimeWindow
  setTimeWindow: (next: TimeWindow) => void
  clearAllFilters: () => void
  statusCounts: Record<string, number>
  sort: SortState<SortKey>
  toggleSort: (key: SortKey) => void
  /** SSE liveness for the page's connection indicator. */
  connected: boolean
  /** Wall-clock ms of the most recent activity frame, or null. */
  lastEventAt: number | null
}

function matchesQuery(session: SessionSummary, query: string): boolean {
  const q = query.toLowerCase()
  return (
    session.id.toLowerCase().includes(q) ||
    (session.workflow_id?.toLowerCase().includes(q) ?? false)
  )
}

export function useSessionList(): UseSessionListResult {
  const [searchParams] = useSearchParams()
  const workflowIdFilter = searchParams.get('workflow_id') ?? ''
  const {
    selectedStatuses,
    timeWindow,
    toggleStatus,
    setTimeWindow,
    clearStatuses,
    clearAll: clearAllFilters,
  } = useFilterUrlState()
  const { sort, toggleSort } = useSortUrlState(SESSION_SORT_CONFIG)

  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')

  const statusesKey = useMemo(
    () => Array.from(selectedStatuses).sort().join(','),
    [selectedStatuses],
  )

  const fetchNow = useCallback(() => {
    const statuses = statusesKey ? statusesKey.split(',') : undefined
    listSessions({
      workflow_id: workflowIdFilter || undefined,
      statuses,
      started_after: timeWindowToStartedAfter(timeWindow),
      limit: 100,
    })
      .then((data) => setSessions(data.sessions))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [workflowIdFilter, statusesKey, timeWindow])

  const scheduleRefetch = useThrottledRefetch(fetchNow, REFETCH_THROTTLE_MS)

  useEffect(() => {
    fetchNow()
  }, [fetchNow])

  const handleFrame = useCallback(
    (frame: SSEEventFrame) => {
      if (frame.type === 'event' && SESSION_LIVE_EVENTS.has(frame.event_type)) {
        scheduleRefetch()
      }
    },
    [scheduleRefetch],
  )

  const { connected, lastEventAt } = useActivityStream({
    onEvent: handleFrame,
    filter: (eventType) => SESSION_LIVE_EVENTS.has(eventType),
  })

  useEffect(() => {
    if (connected) return
    const id = setInterval(fetchNow, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [connected, fetchNow])

  // SSE only fires on Started/Completed, but Lane 2 (tokens/cost/duration)
  // updates continuously. Poll while any row is non-terminal.
  useRefetchWhileRunning({ items: sessions, isTerminal: isTerminalSession, refetch: fetchNow })

  const filteredSessions = useMemo(() => {
    const matched = searchQuery ? sessions.filter((s) => matchesQuery(s, searchQuery)) : sessions
    return sortSessions(matched, sort.key, sort.dir)
  }, [sessions, searchQuery, sort.key, sort.dir])

  const statusCounts = useStatusCounts(sessions)

  return {
    sessions,
    filteredSessions,
    loading,
    searchQuery,
    setSearchQuery,
    selectedStatuses,
    toggleStatus,
    clearStatuses,
    timeWindow,
    setTimeWindow,
    clearAllFilters,
    statusCounts,
    sort,
    toggleSort,
    connected,
    lastEventAt,
  }
}
