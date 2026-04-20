/**
 * Session list data + live updates.
 *
 * Owns all data concerns for the SessionList page:
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
import type { SSEEventFrame, SessionSummary } from '../types'
import { useActivityStream } from './useActivityStream'
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
  statusFilter: string
  setStatusFilter: (status: string) => void
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

  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  const fetchNow = useCallback(() => {
    listSessions({
      workflow_id: workflowIdFilter || undefined,
      status: statusFilter || undefined,
      limit: 100,
    })
      .then((data) => setSessions(data.sessions))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [workflowIdFilter, statusFilter])

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

  return {
    sessions,
    filteredSessions,
    loading,
    searchQuery,
    setSearchQuery,
    statusFilter,
    setStatusFilter,
    connected,
    lastEventAt,
  }
}
