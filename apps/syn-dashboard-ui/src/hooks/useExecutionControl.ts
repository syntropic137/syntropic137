import { useCallback, useEffect, useState } from 'react'
import { cancelExecution, pauseExecution, resumeExecution } from '../api/client'

export type ExecutionState =
  | 'pending'
  | 'running'
  | 'paused'
  | 'cancelled'
  | 'completed'
  | 'failed'
  | 'interrupted'
  | 'unknown'

interface UseExecutionControlResult {
  /** Current execution state (optimistically updated after each command) */
  state: ExecutionState
  /** Last error message */
  error: string | null
  /** Whether a command is in-flight */
  loading: boolean
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
 * React hook for controlling execution via HTTP.
 *
 * State is initialised from the parent's execution.status and optimistically
 * updated after each command so buttons swap immediately without waiting for
 * the next polling cycle.
 */
export function useExecutionControl(
  executionId: string,
  initialState: ExecutionState = 'unknown'
): UseExecutionControlResult {
  const [state, setState] = useState<ExecutionState>(initialState)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Sync whenever the parent refreshes the execution (e.g. SSE/poll cycle)
  useEffect(() => {
    setState(initialState)
  }, [initialState])

  // Pause/cancel are signal-based and async — the returned state is the
  // pre-transition state ("running"), not the post-transition state. Set the
  // target state optimistically on success so buttons swap immediately.
  const pause = useCallback(
    (reason?: string) => {
      setLoading(true)
      setError(null)
      pauseExecution(executionId, reason)
        .then((r) => setState(r.success ? 'paused' : (r.state as ExecutionState)))
        .catch((e: Error) => setError(e.message))
        .finally(() => setLoading(false))
    },
    [executionId]
  )

  const resume = useCallback(() => {
    setLoading(true)
    setError(null)
    resumeExecution(executionId)
      .then((r) => setState(r.success ? 'running' : (r.state as ExecutionState)))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [executionId])

  const cancel = useCallback(
    (reason?: string) => {
      setLoading(true)
      setError(null)
      cancelExecution(executionId, reason)
        .then((r) => setState(r.success ? 'cancelled' : (r.state as ExecutionState)))
        .catch((e: Error) => setError(e.message))
        .finally(() => setLoading(false))
    },
    [executionId]
  )

  return {
    state,
    error,
    loading,
    pause,
    resume,
    cancel,
    canPause: state === 'running' && !loading,
    canResume: state === 'paused' && !loading,
    canCancel: (state === 'running' || state === 'paused') && !loading,
  }
}
