/**
 * Live git event feed.
 *
 * Loads recent git events on mount and subscribes to the shared activity
 * stream (`useActivityStream`) so the dashboard opens at most one
 * `EventSource` per tab even when multiple consumers want activity events.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../api/client'
import { useActivityStream } from './useActivityStream'
import type { SSEEventFrame } from '../types'

export interface GitEvent {
  time: string
  event_type: string
  data: {
    commit_hash?: string
    message?: string
    author?: string
    repository?: string
    branch?: string
    url?: string
    timestamp?: string
  }
}

export interface UseEventFeedResult {
  events: GitEvent[]
  connected: boolean
}

export function useEventFeed(): UseEventFeedResult {
  const [events, setEvents] = useState<GitEvent[]>([])

  useEffect(() => {
    fetch(`${API_BASE}/events/recent?limit=30&event_type=git_commit`)
      .then((r) => r.json())
      .then((data) => {
        if (data.events) setEvents(data.events as GitEvent[])
      })
      .catch(() => {/* non-fatal */})
  }, [])

  const handleFrame = useCallback((frame: SSEEventFrame) => {
    if (frame.type !== 'event') return
    const newEvent: GitEvent = {
      time: frame.timestamp,
      event_type: frame.event_type,
      data: (frame.data ?? {}) as GitEvent['data'],
    }
    setEvents((prev) => [newEvent, ...prev].slice(0, 100))
  }, [])

  const { connected } = useActivityStream({
    onEvent: handleFrame,
    filter: (eventType) => eventType.startsWith('git_'),
  })

  return { events, connected }
}
