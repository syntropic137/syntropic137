/**
 * The React binding for `serialRefreshLoop`: one resource, one request at a
 * time, at a cadence the server can serve (#1095).
 *
 * Everything about the sequencing - what a second ask does while one is
 * outstanding, when the next poll is due, what a hidden tab means - lives in
 * the loop and is documented there. All this file knows is that a component
 * mounts, re-renders with different options, and unmounts.
 *
 * See: ./serialRefreshLoop.ts, docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useEffect, useRef } from 'react'

import {
  createSerialRefreshLoop,
  type SerialRefreshLoop,
  type SerialRefreshOptions,
} from './serialRefreshLoop'

/**
 * Floor for re-reading something that is still running. SSE reports lifecycle
 * transitions; Lane 2 (tokens, cost, duration) moves continuously in between,
 * and this is how often that movement is worth fetching.
 */
export const RUNNING_POLL_INTERVAL_MS = 3000

/**
 * Floor for standing in for a stream that is not connected, so a dropped
 * connection degrades to slow rather than to wrong.
 */
export const DISCONNECTED_POLL_INTERVAL_MS = 5000

export type UseSerialRefreshOptions = SerialRefreshOptions

export interface SerialRefresh {
  /**
   * Ask for fresh data. Runs now if nothing is outstanding, otherwise once the
   * outstanding request finishes. Stable for the lifetime of the component.
   */
  refetch: () => void
}

export function useSerialRefresh({ fetch, pollIntervalMs }: UseSerialRefreshOptions): SerialRefresh {
  const loopRef = useRef<SerialRefreshLoop | null>(null)
  loopRef.current ??= createSerialRefreshLoop({ fetch, pollIntervalMs })
  const loop = loopRef.current

  // Declared before the options effect and not merged with it, because order
  // decides what a StrictMode remount does: the loop has to be live again
  // before the options effect re-times its poll, or the remount would leave a
  // polling surface with no timer.
  useEffect(() => {
    loop.activate()
    return () => loop.deactivate()
  }, [loop])

  useEffect(() => loop.reconfigure({ fetch, pollIntervalMs }), [loop, fetch, pollIntervalMs])

  return { refetch: loop.refetch }
}
