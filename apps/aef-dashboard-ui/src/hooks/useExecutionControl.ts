import { useState, useEffect, useCallback, useRef } from 'react'
import { getControlWebSocketUrl } from '../api/client'

export type ExecutionState = 'pending' | 'running' | 'paused' | 'cancelled' | 'completed' | 'failed' | 'unknown'

interface ControlMessage {
  type: 'state' | 'result' | 'error'
  execution_id?: string
  state?: ExecutionState
  success?: boolean
  message?: string
  error?: string
}

interface UseExecutionControlResult {
  /** Current execution state */
  state: ExecutionState
  /** Whether WebSocket is connected */
  connected: boolean
  /** Last error message */
  error: string | null
  /** Send pause command */
  pause: (reason?: string) => void
  /** Send resume command */
  resume: () => void
  /** Send cancel command */
  cancel: (reason?: string) => void
  /** Whether pause is available */
  canPause: boolean
  /** Whether resume is available */
  canResume: boolean
  /** Whether cancel is available */
  canCancel: boolean
}

/**
 * React hook for controlling execution via WebSocket.
 *
 * @example
 * ```tsx
 * const { state, pause, resume, cancel, canPause, canResume, canCancel } = useExecutionControl(executionId)
 *
 * return (
 *   <div>
 *     <p>State: {state}</p>
 *     {canPause && <button onClick={() => pause()}>Pause</button>}
 *     {canResume && <button onClick={() => resume()}>Resume</button>}
 *     {canCancel && <button onClick={() => cancel()}>Cancel</button>}
 *   </div>
 * )
 * ```
 */
export function useExecutionControl(executionId: string): UseExecutionControlResult {
  const [state, setState] = useState<ExecutionState>('unknown')
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    // Get WebSocket URL from centralized API client
    const wsUrl = getControlWebSocketUrl(executionId)

    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      setConnected(true)
      setError(null)
    }

    ws.onclose = () => {
      setConnected(false)
    }

    ws.onerror = () => {
      setError('WebSocket connection failed')
      setConnected(false)
    }

    ws.onmessage = (event) => {
      try {
        const msg: ControlMessage = JSON.parse(event.data)

        if (msg.type === 'state' && msg.state) {
          setState(msg.state)
        } else if (msg.type === 'result') {
          // Update state from result
          if (msg.state) {
            setState(msg.state as ExecutionState)
          }
          // Clear any previous error on successful result
          if (msg.success) {
            setError(null)
          }
        } else if (msg.type === 'error') {
          setError(msg.error || 'Unknown error')
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e)
      }
    }

    wsRef.current = ws

    // Cleanup on unmount
    return () => {
      ws.close()
    }
  }, [executionId])

  const sendCommand = useCallback((command: string, options?: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ command, ...options }))
    } else {
      setError('WebSocket not connected')
    }
  }, [])

  const pause = useCallback((reason?: string) => {
    sendCommand('pause', reason ? { reason } : {})
  }, [sendCommand])

  const resume = useCallback(() => {
    sendCommand('resume')
  }, [sendCommand])

  const cancel = useCallback((reason?: string) => {
    sendCommand('cancel', reason ? { reason } : {})
  }, [sendCommand])

  return {
    state,
    connected,
    error,
    pause,
    resume,
    cancel,
    canPause: state === 'running',
    canResume: state === 'paused',
    canCancel: state === 'running' || state === 'paused',
  }
}
