/**
 * Live-connection status dot for SSE-driven pages.
 *
 * Green when the shared activity stream is connected, amber when the page is
 * relying on the polling fallback. Hover reveals the time of the last frame.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { clsx } from 'clsx'

interface ConnectionIndicatorProps {
  connected: boolean
  lastEventAt: number | null
}

function formatLastEvent(lastEventAt: number | null): string {
  if (lastEventAt === null) return 'No events yet'
  const seconds = Math.max(0, Math.round((Date.now() - lastEventAt) / 1000))
  if (seconds < 1) return 'Last event just now'
  if (seconds < 60) return `Last event ${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `Last event ${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  return `Last event ${hours}h ago`
}

export function ConnectionIndicator({ connected, lastEventAt }: ConnectionIndicatorProps) {
  const title = connected ? formatLastEvent(lastEventAt) : 'Disconnected (polling fallback)'
  const label = connected ? 'Live' : 'Polling'

  return (
    <span
      title={title}
      className="inline-flex items-center gap-2 text-xs text-slate-400"
      aria-live="polite"
    >
      <span
        className={clsx(
          'inline-block h-2 w-2 rounded-full',
          connected ? 'bg-emerald-500' : 'bg-amber-500',
          connected && 'animate-pulse',
        )}
      />
      <span>{label}</span>
    </span>
  )
}

export default ConnectionIndicator
