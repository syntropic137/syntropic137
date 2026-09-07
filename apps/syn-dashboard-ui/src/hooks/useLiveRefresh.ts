/**
 * Keeps a list current without the operator asking.
 *
 * Three triggers behind one name, because a surface that wires up only some of
 * them looks live and goes stale:
 *
 *   - SSE frames for the event types that mean THIS list changed. They arrive
 *     in bursts, so refetching is throttled.
 *   - A poll while the stream is down, so a dropped connection degrades to
 *     slow rather than to wrong.
 *   - A faster poll while any row on the page is still moving. SSE only fires
 *     on Started/Completed, but Lane 2 (tokens, cost, duration) updates
 *     continuously in between.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useEffect } from 'react'
import type { SSEEventFrame } from '../types'
import { useActivityStream } from './useActivityStream'
import { useRefetchWhileRunning } from './useRefetchWhileRunning'
import { useThrottledRefetch } from './useThrottledRefetch'

const REFETCH_THROTTLE_MS = 500
const POLL_INTERVAL_MS = 5000

export interface UseLiveRefreshOptions<TRow> {
  refetch: () => void
  /** Event types that mean "this list changed". */
  liveEvents: ReadonlySet<string>
  /** The rows currently on screen - what "still moving" is judged over. */
  rows: TRow[]
  /** False while a row's Lane 2 numbers are still moving, which keeps polling. */
  isTerminal: (row: TRow) => boolean
}

export interface LiveRefreshState {
  connected: boolean
  lastEventAt: number | null
}

export function useLiveRefresh<TRow>({
  refetch,
  liveEvents,
  rows,
  isTerminal,
}: UseLiveRefreshOptions<TRow>): LiveRefreshState {
  const scheduleRefetch = useThrottledRefetch(refetch, REFETCH_THROTTLE_MS)

  const handleFrame = useCallback(
    (frame: SSEEventFrame) => {
      if (frame.type === 'event' && liveEvents.has(frame.event_type)) scheduleRefetch()
    },
    [liveEvents, scheduleRefetch],
  )

  const { connected, lastEventAt } = useActivityStream({
    onEvent: handleFrame,
    filter: (eventType) => liveEvents.has(eventType),
  })

  useEffect(() => {
    if (connected) return
    const id = setInterval(refetch, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [connected, refetch])

  useRefetchWhileRunning({ items: rows, isTerminal, refetch })

  return { connected, lastEventAt }
}
