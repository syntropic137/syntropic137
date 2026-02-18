import { useEffect, useRef, useState } from 'react'
import { Activity, ExternalLink, GitCommit, GitMerge, Wifi, WifiOff } from 'lucide-react'

interface GitEvent {
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

function shortHash(hash: string | undefined): string {
  return hash ? hash.slice(0, 7) : '???????'
}

function relativeTime(isoString: string | undefined): string {
  if (!isoString) return ''
  const diff = Date.now() - new Date(isoString).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function EventRow({ event }: { event: GitEvent }) {
  const { data, event_type } = event
  const isCommit = event_type === 'git_commit'
  const Icon = isCommit ? GitCommit : GitMerge

  return (
    <div className="flex items-start gap-2.5 px-3 py-2.5 hover:bg-[var(--color-bg-secondary)] transition-colors">
      <Icon className="h-3.5 w-3.5 mt-0.5 shrink-0 text-[var(--color-text-muted)]" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 flex-wrap">
          <code className="text-xs font-mono text-[var(--color-accent)]">
            {shortHash(data.commit_hash)}
          </code>
          {data.branch && (
            <span className="text-xs text-[var(--color-text-muted)]">
              {data.repository?.split('/')[1] ?? data.repository} · {data.branch}
            </span>
          )}
          <span className="text-xs text-[var(--color-text-muted)] ml-auto shrink-0">
            {relativeTime(data.timestamp ?? event.time)}
          </span>
        </div>
        <p className="text-xs text-[var(--color-text-primary)] truncate mt-0.5">
          {data.message ?? '—'}
        </p>
        {data.author && (
          <p className="text-xs text-[var(--color-text-muted)] mt-0.5">{data.author}</p>
        )}
      </div>
      {data.url && (
        <a
          href={data.url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors"
          title="View on GitHub"
        >
          <ExternalLink className="h-3 w-3" />
        </a>
      )}
    </div>
  )
}

export function EventFeed() {
  const [events, setEvents] = useState<GitEvent[]>([])
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  // Load recent events on mount
  useEffect(() => {
    fetch('/api/events/recent?limit=30')
      .then((r) => r.json())
      .then((data) => {
        if (data.events) setEvents(data.events as GitEvent[])
      })
      .catch(() => {/* non-fatal */})
  }, [])

  // Connect to global activity WebSocket
  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/activity`)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setConnected(false)

    ws.onmessage = (msg) => {
      try {
        const parsed = JSON.parse(msg.data)
        if (parsed.type === 'event' && parsed.event_type?.startsWith('git_')) {
          const newEvent: GitEvent = {
            time: parsed.timestamp ?? new Date().toISOString(),
            event_type: parsed.event_type,
            data: parsed.data ?? {},
          }
          setEvents((prev) => [newEvent, ...prev].slice(0, 100))
        }
      } catch {
        // ignore malformed messages
      }
    }

    return () => ws.close()
  }, [])

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--color-border)] p-3 shrink-0">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-[var(--color-text-secondary)]" />
          <span className="text-sm font-medium text-[var(--color-text-primary)]">
            Live Events
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {connected ? (
            <Wifi className="h-3 w-3 text-green-500" />
          ) : (
            <WifiOff className="h-3 w-3 text-[var(--color-text-muted)]" />
          )}
          <span className="text-xs text-[var(--color-text-muted)]">
            {connected ? 'live' : 'offline'}
          </span>
        </div>
      </div>

      {/* Event list */}
      <div className="flex-1 overflow-y-auto divide-y divide-[var(--color-border)]">
        {events.length === 0 ? (
          <div className="flex items-center justify-center h-full p-4">
            <p className="text-xs text-[var(--color-text-muted)] text-center">
              No git events yet.
              <br />
              Push a commit to see it here.
            </p>
          </div>
        ) : (
          events.map((event, i) => <EventRow key={`${event.data.commit_hash ?? i}-${i}`} event={event} />)
        )}
      </div>
    </div>
  )
}
