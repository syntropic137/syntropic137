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

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listSessions } from '../api/sessions'
import type { SSEEventFrame, SessionSummary } from '../types'
import { useActivityStream } from './useActivityStream'

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

export function useSessionList(): UseSessionListResult {
  const [searchParams] = useSearchParams()
  const workflowIdFilter = searchParams.get('workflow_id') ?? ''

  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  const lastFetchRef = useRef<number>(0)
  const pendingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchNow = useCallback(() => {
    lastFetchRef.current = Date.now()
    listSessions({
      workflow_id: workflowIdFilter || undefined,
      status: statusFilter || undefined,
      limit: 100,
    })
      .then((data) => {
        setSessions(data.sessions)
        setLoading(false)
      })
      .catch((err) => {
        console.error(err)
        setLoading(false)
      })
  }, [workflowIdFilter, statusFilter])

  const scheduleRefetch = useCallback(() => {
    const elapsed = Date.now() - lastFetchRef.current
    if (elapsed >= REFETCH_THROTTLE_MS) {
      fetchNow()
      return
    }
    if (pendingTimerRef.current !== null) return
    pendingTimerRef.current = setTimeout(() => {
      pendingTimerRef.current = null
      fetchNow()
    }, REFETCH_THROTTLE_MS - elapsed)
  }, [fetchNow])

  // Initial load + refetch when filters change.
  useEffect(() => {
    fetchNow()
    return () => {
      if (pendingTimerRef.current !== null) {
        clearTimeout(pendingTimerRef.current)
        pendingTimerRef.current = null
      }
    }
  }, [fetchNow])

  // Live updates via shared activity stream.
  const handleFrame = useCallback(
    (frame: SSEEventFrame) => {
      if (frame.type !== 'event') return
      if (!SESSION_LIVE_EVENTS.has(frame.event_type)) return
      scheduleRefetch()
    },
    [scheduleRefetch],
  )

  const { connected, lastEventAt } = useActivityStream({
    onEvent: handleFrame,
    filter: (eventType) => SESSION_LIVE_EVENTS.has(eventType),
  })

  // Polling fallback: only when SSE is disconnected.
  useEffect(() => {
    if (connected) return
    const id = setInterval(fetchNow, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [connected, fetchNow])

  const filteredSessions = useMemo(
    () =>
      searchQuery
        ? sessions.filter(
            (s) =>
              s.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
              s.workflow_id?.toLowerCase().includes(searchQuery.toLowerCase()),
          )
        : sessions,
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
