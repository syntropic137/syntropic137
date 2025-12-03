import { clsx } from 'clsx'
import { Activity, CheckCircle2, Clock, Play, XCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { getRecentEvents, subscribeToEvents } from '../api/client'
import type { EventMessage } from '../types'

const eventIcons: Record<string, typeof Activity> = {
  workflow_started: Play,
  workflow_completed: CheckCircle2,
  workflow_failed: XCircle,
  phase_started: Clock,
  phase_completed: CheckCircle2,
  phase_failed: XCircle,
  session_started: Play,
  session_completed: CheckCircle2,
  default: Activity,
}

const eventColors: Record<string, string> = {
  workflow_started: 'text-blue-400',
  workflow_completed: 'text-emerald-400',
  workflow_failed: 'text-red-400',
  phase_started: 'text-blue-400',
  phase_completed: 'text-emerald-400',
  phase_failed: 'text-red-400',
  session_started: 'text-indigo-400',
  session_completed: 'text-emerald-400',
  default: 'text-[var(--color-text-secondary)]',
}

function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function formatEventType(type: string): string {
  return type.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

export function EventFeed() {
  const [events, setEvents] = useState<EventMessage[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const feedRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // Load recent events
    getRecentEvents()
      .then(setEvents)
      .catch(console.error)

    // Subscribe to live events
    const unsubscribe = subscribeToEvents(
      (event) => {
        setEvents((prev) => [...prev.slice(-49), event])
      },
      () => setIsConnected(false),
      () => setIsConnected(true) // onConnected callback
    )

    return unsubscribe
  }, [])

  useEffect(() => {
    // Auto-scroll to bottom on new events
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight
    }
  }, [events])

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--color-border)] p-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-[var(--color-text-secondary)]" />
          <span className="text-sm font-medium text-[var(--color-text-primary)]">
            Live Events
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className={clsx(
              'h-2 w-2 rounded-full',
              isConnected ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'
            )}
          />
          <span className="text-xs text-[var(--color-text-muted)]">
            {isConnected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
      </div>

      {/* Event list */}
      <div
        ref={feedRef}
        className="flex-1 overflow-y-auto p-2 space-y-1"
      >
        {events.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-[var(--color-text-muted)]">
            Waiting for events...
          </div>
        ) : (
          events.map((event, idx) => {
            const Icon = eventIcons[event.event_type] ?? eventIcons.default
            const color = eventColors[event.event_type] ?? eventColors.default

            return (
              <div
                key={`${event.timestamp}-${idx}`}
                className="flex items-start gap-2 rounded-md p-2 text-xs transition-colors hover:bg-[var(--color-surface-elevated)] animate-fade-in"
              >
                <Icon className={clsx('mt-0.5 h-3.5 w-3.5 flex-shrink-0', color)} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-[var(--color-text-primary)]">
                      {formatEventType(event.event_type)}
                    </span>
                    <span className="text-[var(--color-text-muted)]">
                      {formatTime(event.timestamp)}
                    </span>
                  </div>
                  {(event.workflow_id || event.phase_id || event.session_id) && (
                    <div className="mt-0.5 truncate text-[var(--color-text-secondary)]">
                      {event.workflow_id && <span>wf:{event.workflow_id.slice(0, 8)}</span>}
                      {event.phase_id && <span className="ml-2">ph:{event.phase_id}</span>}
                      {event.session_id && <span className="ml-2">sess:{event.session_id.slice(0, 8)}</span>}
                    </div>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
