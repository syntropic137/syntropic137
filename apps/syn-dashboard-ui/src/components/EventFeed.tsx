import { Activity, Wifi, WifiOff } from 'lucide-react'

/**
 * EventFeed component - now shows guidance about real-time events.
 *
 * Real-time events have moved from SSE to WebSocket and are now
 * available on individual execution detail pages via useExecutionStream.
 */
export function EventFeed() {
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
          <WifiOff className="h-3 w-3 text-[var(--color-text-muted)]" />
          <span className="text-xs text-[var(--color-text-muted)]">
            Per-execution
          </span>
        </div>
      </div>

      {/* Info message */}
      <div className="flex-1 flex items-center justify-center p-4">
        <div className="text-center space-y-2">
          <Wifi className="h-8 w-8 mx-auto text-[var(--color-text-muted)]" />
          <p className="text-sm text-[var(--color-text-secondary)]">
            Real-time events are now available on execution detail pages
          </p>
          <p className="text-xs text-[var(--color-text-muted)]">
            Open an execution to see live WebSocket updates
          </p>
        </div>
      </div>
    </div>
  )
}
