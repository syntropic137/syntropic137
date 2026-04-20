/**
 * Shared SSE subscription to the global activity feed.
 *
 * A single EventSource per browser tab is multiplexed across every consumer,
 * so opening the dashboard in N tabs costs N connections rather than N times
 * the number of features that listen for live events. The connection opens on
 * first subscriber and closes when the last subscriber unmounts.
 *
 * Consumers register a callback (and optional event-type filter) and receive
 * `{ connected, lastEventAt }` for live status indicators.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useEffect, useRef, useState } from 'react'
import { API_BASE } from '../api/client'
import type { SSEEventFrame } from '../types'

type FrameHandler = (frame: SSEEventFrame) => void

interface Subscriber {
  handler: FrameHandler
  filter?: (eventType: string) => boolean
}

// ---------------------------------------------------------------------------
// Module-scoped state — one EventSource shared by every consumer in this tab.
// ---------------------------------------------------------------------------

let source: EventSource | null = null
let connected = false
let lastEventAt: number | null = null
const subscribers = new Set<Subscriber>()
const stateListeners = new Set<() => void>()

function notifyStateListeners(): void {
  for (const listener of stateListeners) listener()
}

function dispatchFrame(frame: SSEEventFrame): void {
  for (const sub of subscribers) {
    if (sub.filter && !sub.filter(frame.event_type)) continue
    try {
      sub.handler(frame)
    } catch {
      // never let one consumer's error tear down the connection
    }
  }
}

function ensureConnection(): void {
  if (source) return
  source = new EventSource(`${API_BASE}/sse/activity`)

  source.onopen = () => {
    connected = true
    notifyStateListeners()
  }
  source.onerror = () => {
    connected = false
    notifyStateListeners()
  }
  source.onmessage = (e: MessageEvent<string>) => {
    try {
      const frame = JSON.parse(e.data) as SSEEventFrame
      lastEventAt = Date.now()
      dispatchFrame(frame)
      notifyStateListeners()
    } catch {
      // malformed frame — ignore
    }
  }
}

function teardownConnection(): void {
  if (!source) return
  source.close()
  source = null
  connected = false
  notifyStateListeners()
}

// ---------------------------------------------------------------------------
// Test-only reset — used by useActivityStream.test.ts to start with a clean
// slate. Not exported for production code.
// ---------------------------------------------------------------------------

export function __resetActivityStreamForTests(): void {
  teardownConnection()
  subscribers.clear()
  stateListeners.clear()
  lastEventAt = null
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseActivityStreamOptions {
  /** Invoked for every frame matching the optional filter. */
  onEvent?: FrameHandler
  /** Optional predicate; only frames whose event_type passes are dispatched. */
  filter?: (eventType: string) => boolean
}

export interface UseActivityStreamResult {
  /** Whether the underlying EventSource is open. */
  connected: boolean
  /** Wall-clock ms of the most recent frame, or null if none yet. */
  lastEventAt: number | null
}

/**
 * Subscribe to the shared `/sse/activity` stream.
 *
 * Mounting the hook adds a subscriber and (if needed) opens the shared
 * EventSource. Unmounting removes the subscriber and closes the connection
 * when no consumers remain.
 */
export function useActivityStream(
  options: UseActivityStreamOptions = {},
): UseActivityStreamResult {
  const { onEvent, filter } = options

  // Snapshot module-scoped state into React state so re-renders see updates.
  const [state, setState] = useState<UseActivityStreamResult>({
    connected,
    lastEventAt,
  })

  // Keep the latest callback in a ref so swapping it never tears down the
  // shared connection.
  const onEventRef = useRef(onEvent)
  const filterRef = useRef(filter)
  useEffect(() => {
    onEventRef.current = onEvent
    filterRef.current = filter
  }, [onEvent, filter])

  useEffect(() => {
    const subscriber: Subscriber = {
      handler: (frame) => onEventRef.current?.(frame),
      filter: (eventType) => (filterRef.current ? filterRef.current(eventType) : true),
    }
    subscribers.add(subscriber)

    const stateListener = () => {
      setState({ connected, lastEventAt })
    }
    stateListeners.add(stateListener)

    ensureConnection()
    // Sync immediately in case the connection is already open.
    stateListener()

    return () => {
      subscribers.delete(subscriber)
      stateListeners.delete(stateListener)
      if (subscribers.size === 0) teardownConnection()
    }
  }, [])

  return state
}

export default useActivityStream
