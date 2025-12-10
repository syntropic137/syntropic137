/**
 * Hook for real-time execution event streaming via WebSocket.
 *
 * This replaces the old SSE-based subscribeToEvents with a WebSocket
 * connection that receives domain events from the RealTimeProjection.
 *
 * Event flow:
 *   Event Store → Subscription → ProjectionManager → RealTimeProjection → WebSocket → This Hook
 *
 * Usage:
 *   const { isConnected, events, latestEvent } = useExecutionStream(executionId)
 */

import { useCallback, useEffect, useRef, useState } from 'react'

/** Event message from WebSocket */
export interface ExecutionEvent {
  type: 'connected' | 'event' | 'error'
  event_type?: string
  execution_id?: string
  data?: Record<string, unknown>
  timestamp?: string
  message?: string
  error?: string
}

/** Options for the hook */
export interface UseExecutionStreamOptions {
  /** Callback when an event is received */
  onEvent?: (event: ExecutionEvent) => void
  /** Auto-reconnect on disconnect (default: true) */
  autoReconnect?: boolean
  /** Reconnect delay in ms (default: 2000) */
  reconnectDelay?: number
}

/** Return type for the hook */
export interface UseExecutionStreamResult {
  /** Whether WebSocket is connected */
  isConnected: boolean
  /** All events received */
  events: ExecutionEvent[]
  /** Most recent event */
  latestEvent: ExecutionEvent | null
  /** Send a command to the server (future: pause/resume/cancel) */
  sendCommand: (command: string, payload?: Record<string, unknown>) => void
}

/**
 * Hook for streaming execution events via WebSocket.
 *
 * @param executionId - The execution ID to subscribe to
 * @param options - Configuration options
 */
export function useExecutionStream(
  executionId: string | undefined,
  options: UseExecutionStreamOptions = {}
): UseExecutionStreamResult {
  const { onEvent, autoReconnect = true, reconnectDelay = 2000 } = options

  const [isConnected, setIsConnected] = useState(false)
  const [events, setEvents] = useState<ExecutionEvent[]>([])
  const [latestEvent, setLatestEvent] = useState<ExecutionEvent | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<number | null>(null)

  // Clean up reconnect timeout
  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current !== null) {
      window.clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
  }, [])

  // Send command to server
  const sendCommand = useCallback(
    (command: string, payload: Record<string, unknown> = {}) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ command, ...payload }))
      }
    },
    []
  )

  // Connect to WebSocket
  useEffect(() => {
    if (!executionId) return

    const connect = () => {
      // Determine WebSocket URL based on current protocol
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${protocol}//${window.location.host}/ws/executions/${executionId}`

      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        console.log(`[WebSocket] Connected to execution ${executionId}`)
        setIsConnected(true)
        clearReconnectTimeout()
      }

      ws.onmessage = (messageEvent) => {
        try {
          const event: ExecutionEvent = JSON.parse(messageEvent.data)

          // Update state
          setEvents((prev) => [...prev, event])
          setLatestEvent(event)

          // Call user callback
          onEvent?.(event)

          // Log event type
          if (event.type === 'connected') {
            console.log(`[WebSocket] Subscribed to execution ${event.execution_id}`)
          } else if (event.type === 'event') {
            console.log(`[WebSocket] Event: ${event.event_type}`, event.data)
          }
        } catch (e) {
          console.error('[WebSocket] Failed to parse message:', e)
        }
      }

      ws.onerror = (error) => {
        console.error('[WebSocket] Error:', error)
      }

      ws.onclose = (closeEvent) => {
        console.log(`[WebSocket] Disconnected (code: ${closeEvent.code})`)
        setIsConnected(false)
        wsRef.current = null

        // Auto-reconnect if enabled
        if (autoReconnect && !closeEvent.wasClean) {
          console.log(`[WebSocket] Reconnecting in ${reconnectDelay}ms...`)
          reconnectTimeoutRef.current = window.setTimeout(connect, reconnectDelay)
        }
      }
    }

    connect()

    // Cleanup on unmount or executionId change
    return () => {
      clearReconnectTimeout()
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounted')
        wsRef.current = null
      }
    }
  }, [executionId, autoReconnect, reconnectDelay, onEvent, clearReconnectTimeout])

  return {
    isConnected,
    events,
    latestEvent,
    sendCommand,
  }
}

export default useExecutionStream
