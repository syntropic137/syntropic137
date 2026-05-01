/**
 * Hook for real-time execution event streaming via Server-Sent Events.
 *
 * Replaces the previous WebSocket-based implementation. The SSE endpoint
 * is strictly server-to-client, making EventSource the correct fit:
 * - Native browser reconnect (no manual retry loop required)
 * - Plain HTTP — works through all proxies and load balancers
 * - No extra dependency
 *
 * Event flow:
 *   Event Store → Subscription → ProjectionManager → RealTimeProjection → SSE → This Hook
 *
 * Usage:
 *   const { isConnected, events, latestEvent } = useExecutionStream(executionId)
 */

import { useEffect, useRef, useState } from 'react'
import { API_BASE } from '../api/client'
import type { SSEEventFrame } from '../types'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type { SSEEventFrame }

/** Options for the hook */
export interface UseExecutionStreamOptions {
  /** Callback invoked for every frame received (including connected/terminal). */
  onEvent?: (frame: SSEEventFrame) => void
}

/** Return type for the hook */
export interface UseExecutionStreamResult {
  /** Whether the EventSource is currently open. */
  isConnected: boolean
  /** All frames received since mount. */
  events: SSEEventFrame[]
  /** Most recent frame. */
  latestEvent: SSEEventFrame | null
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Stream execution events for *executionId* via SSE.
 *
 * The EventSource reconnects automatically on network interruptions.
 * The stream closes server-side when a terminal event (WorkflowCompleted /
 * WorkflowFailed) is broadcast; the hook reflects this via ``isConnected``.
 *
 * @param executionId - The execution to subscribe to (undefined → no-op).
 * @param options     - Optional callback configuration.
 */
export function useExecutionStream(
  executionId: string | undefined,
  options: UseExecutionStreamOptions = {},
): UseExecutionStreamResult {
  const { onEvent } = options

  const [isConnected, setIsConnected] = useState(false)
  const [events, setEvents] = useState<SSEEventFrame[]>([])
  const [latestEvent, setLatestEvent] = useState<SSEEventFrame | null>(null)

  const sourceRef = useRef<EventSource | null>(null)
  // Keep callback in a ref so changing it never triggers a reconnect.
  const onEventRef = useRef(onEvent)
  useEffect(() => {
    onEventRef.current = onEvent
  }, [onEvent])

  useEffect(() => {
    if (!executionId) return

    const url = `${API_BASE}/sse/executions/${executionId}`
    const source = new EventSource(url)
    sourceRef.current = source

    source.onopen = () => {
      setIsConnected(true)
    }

    source.onerror = () => {
      // EventSource sets readyState to CONNECTING and retries automatically.
      // We reflect the momentary gap in isConnected.
      setIsConnected(false)
    }

    source.onmessage = (e: MessageEvent<string>) => {
      try {
        const frame = JSON.parse(e.data) as SSEEventFrame
        setEvents((prev) => [...prev, frame])
        setLatestEvent(frame)
        onEventRef.current?.(frame)

        if (frame.type === 'terminal') {
          // Server closed the stream; no further reconnect needed.
          source.close()
          setIsConnected(false)
        }
      } catch {
        // Ignore malformed frames — keepalive comments never reach onmessage.
      }
    }

    return () => {
      source.close()
      sourceRef.current = null
      setIsConnected(false)
    }
  }, [executionId])

  return { isConnected, events, latestEvent }
}

export default useExecutionStream
