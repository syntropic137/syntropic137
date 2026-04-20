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
import { useActivityStream } from './useActivityStream'
import { timeWindowToStartedAfter, useFilterUrlState } from './useFilterUrlState'
import { useStatusCounts } from './useStatusCounts'
import { useThrottledRefetch } from './useThrottledRefetch'

const REFETCH_THROTTLE_MS = 500
const POLL_INTERVAL_MS = 5000
const SESSION_LIVE_EVENTS = new Set(['SessionStarted', 'SessionCompleted'])

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

  const filteredSessions = useMemo(
    () => (searchQuery ? sessions.filter((s) => matchesQuery(s, searchQuery)) : sessions),
    [sessions, searchQuery],
  )

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
    connected,
    lastEventAt,
  }
}
