import { useCallback, useEffect, useState } from 'react'
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

// States that represent a terminal or in-flight transition we own locally.
// The parent's polling should not override these until the projection confirms
// a real terminal state.
const TERMINAL_STATES = new Set<ExecutionState>([
  'cancelling',
  'cancelled',
  'completed',
  'failed',
  'interrupted',
])

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
 * State is initialised from the parent's execution.status. After cancel is
 * confirmed by the API the state moves to 'cancelling' and ignores parent
 * polling until the projection confirms a terminal state — preventing the
 * race where an immediate refresh overwrites the optimistic state.
 */
export function useExecutionControl(
  executionId: string,
  initialState: ExecutionState = 'unknown',
  onSuccess?: () => void
): UseExecutionControlResult {
  const [state, setState] = useState<ExecutionState>(initialState)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Sync from parent polling, but don't let it override a locally-set terminal
  // or in-flight state. Only accept parent updates once the projection itself
  // reaches a terminal state (projection has caught up).
  useEffect(() => {
    setState((prev) => {
      if (TERMINAL_STATES.has(prev)) {
        // Only accept the parent update once the projection confirms terminal
        return PROJECTION_TERMINAL_STATES.has(initialState) ? initialState : prev
      }
      return initialState
    })
  }, [initialState])

  const cancel = useCallback(
    (reason?: string) => {
      setLoading(true)
      setError(null)
      cancelExecution(executionId, reason)
        .then((r) => {
          if (r.success) {
            // Move to 'cancelling' — the signal is queued but the projection
            // won't reflect the change until the container actually stops.
            // Don't call onSuccess here: an immediate refresh would fetch
            // stale 'running' state and undo this update.
            setState('cancelling')
          } else {
            setError(r.error ?? `Cannot cancel: ${r.state}`)
          }
        })
        .catch((e: Error) => setError(e.message))
        .finally(() => setLoading(false))
    },
    [executionId]
  )

  // onSuccess is kept in the signature for API compatibility but is intentionally
  // not called on cancel — see comment above.
  void onSuccess

  return {
    state,
    error,
    loading,
    cancel,
    canCancel: (state === 'running' || state === 'paused') && !loading,
  }
}
