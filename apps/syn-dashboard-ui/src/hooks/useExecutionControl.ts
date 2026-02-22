import { useCallback, useState } from 'react'
import { cancelExecution } from '../api/client'

export type ExecutionState =
  | 'pending'
  | 'running'
  | 'paused'
  | 'cancelled'
  | 'cancelling' // UI-only: cancel sent, waiting for projection to confirm
  | 'completed'
  | 'failed'
  | 'interrupted'
  | 'unknown'

// States where the projection has caught up — safe to defer back to parent.
const PROJECTION_TERMINAL_STATES = new Set<ExecutionState>([
  'cancelled',
  'completed',
  'failed',
  'interrupted',
])

interface UseExecutionControlResult {
  /** Current execution state (optimistically updated after cancel) */
  state: ExecutionState
  /** Last error message */
  error: string | null
  /** Whether a command is in-flight */
  loading: boolean
  /** Send cancel command */
  cancel: (reason?: string) => void
  /** Whether cancel is available */
  canCancel: boolean
}

/**
 * React hook for cancelling a running execution via HTTP.
 *
 * After cancel is confirmed by the API the local commandState moves to
 * 'cancelling'. The displayed state is derived: while commandState is set
 * and the parent projection hasn't reached a terminal state, we show
 * commandState (preventing the flicker where a stale refresh overwrites
 * the optimistic update). Once the projection confirms a terminal state,
 * we defer back to the parent.
 */
export function useExecutionControl(
  executionId: string,
  initialState: ExecutionState = 'unknown'
): UseExecutionControlResult {
  // Tracks the local command outcome. null = no command sent yet.
  const [commandState, setCommandState] = useState<ExecutionState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Derived state: once we've sent a cancel, hold the local commandState until
  // the projection itself reaches a terminal state (meaning it has caught up).
  const state: ExecutionState =
    commandState !== null && !PROJECTION_TERMINAL_STATES.has(initialState)
      ? commandState
      : initialState

  const cancel = useCallback(
    (reason?: string) => {
      setLoading(true)
      setError(null)
      cancelExecution(executionId, reason)
        .then((r) => {
          if (r.success) {
            setCommandState('cancelling')
          } else {
            setError(r.error ?? `Cannot cancel: ${r.state}`)
          }
        })
        .catch((e: Error) => setError(e.message))
        .finally(() => setLoading(false))
    },
    [executionId]
  )

  return {
    state,
    error,
    loading,
    cancel,
    canCancel: (state === 'running' || state === 'paused') && !loading,
  }
}
