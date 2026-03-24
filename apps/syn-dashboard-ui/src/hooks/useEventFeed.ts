import { useEffect, useState } from 'react'
import { API_BASE } from '../api/client'

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

/**
 * Hook to manage the live event feed: fetches recent events on mount
 * and subscribes to SSE for real-time updates.
 */
export function useEventFeed(): UseEventFeedResult {
  const [events, setEvents] = useState<GitEvent[]>([])
  const [connected, setConnected] = useState(false)

  // Load recent events on mount
  useEffect(() => {
    fetch(`${API_BASE}/events/recent?limit=30`)
      .then((r) => r.json())
      .then((data) => {
        if (data.events) setEvents(data.events as GitEvent[])
      })
      .catch(() => {/* non-fatal */})
  }, [])

  // Connect to global activity SSE feed
  useEffect(() => {
    const source = new EventSource(`${API_BASE}/sse/activity`)

    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)

    source.onmessage = (e: MessageEvent<string>) => {
      try {
        const parsed = JSON.parse(e.data) as {
          type: string
          event_type?: string
          timestamp?: string
          data?: Record<string, unknown>
        }
        if (parsed.type === 'event' && parsed.event_type?.startsWith('git_')) {
          const newEvent: GitEvent = {
            time: parsed.timestamp ?? new Date().toISOString(),
            event_type: parsed.event_type,
            data: (parsed.data ?? {}) as GitEvent['data'],
          }
          setEvents((prev) => [newEvent, ...prev].slice(0, 100))
        }
      } catch {
        // ignore malformed frames
      }
    }

    return () => source.close()
  }, [])

  return { events, connected }
}
