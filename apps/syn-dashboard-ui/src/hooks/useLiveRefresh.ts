/**
 * When a list should ask the server again.
 *
 * Three reasons, because a surface that wires up only some of them looks live
 * and goes stale:
 *
 *   - SSE frames for the event types that mean THIS list changed. They arrive
 *     in bursts, so refetching is throttled.
 *   - While the stream is down, a poll, so a dropped connection degrades to
 *     slow rather than to wrong.
 *   - While any row on the page is still moving, a faster poll. SSE only fires
 *     on Started/Completed, but Lane 2 (tokens, cost, duration) updates
 *     continuously in between.
 *
 * What this no longer does is run the clock. It used to hold two `setInterval`s
 * that called `refetch()` and could not tell whether the previous call had come
 * back, so a slow endpoint got overlapping queries from both of them at once
 * (#1095). The cadence is now a number this hands to `useSerialRefresh`, which
 * owns the single in-flight request for the list and spaces polls by what the
 * endpoint is actually costing. The policy stayed here; the timers went.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback } from 'react'
import type { SSEEventFrame } from '../types'
import { useActivityStream } from './useActivityStream'
import { useThrottledRefetch } from './useThrottledRefetch'
import { DISCONNECTED_POLL_INTERVAL_MS, RUNNING_POLL_INTERVAL_MS } from './useSerialRefresh'

const REFETCH_THROTTLE_MS = 500

export interface UseLiveRefreshOptions {
  /** Called when SSE reports a change to this list. Bursts are coalesced. */
  onChanged: () => void
  /** Event types that mean "this list changed". */
  liveEvents: ReadonlySet<string>
}

export interface LiveRefreshState {
  connected: boolean
  lastEventAt: number | null
}

/**
 * How often this list may poll, given what is on screen and whether the stream
 * is up. `null` means SSE alone is enough and no timer is needed.
 *
 * This is a floor, not a period: `useSerialRefresh` waits longer when the
 * endpoint is answering slowly, which is the whole point of #1095.
 */
export function listPollIntervalMs<TRow>(
  rows: TRow[],
  isTerminal: (row: TRow) => boolean,
  connected: boolean,
): number | null {
  if (rows.some((row) => !isTerminal(row))) return RUNNING_POLL_INTERVAL_MS
  if (!connected) return DISCONNECTED_POLL_INTERVAL_MS
  return null
}

export function useLiveRefresh({ onChanged, liveEvents }: UseLiveRefreshOptions): LiveRefreshState {
  const scheduleRefetch = useThrottledRefetch(onChanged, REFETCH_THROTTLE_MS)

  const handleFrame = useCallback(
    (frame: SSEEventFrame) => {
      if (frame.type === 'event' && liveEvents.has(frame.event_type)) scheduleRefetch()
    },
    [liveEvents, scheduleRefetch],
  )

  return useActivityStream({
    onEvent: handleFrame,
    filter: (eventType) => liveEvents.has(eventType),
  })
}
