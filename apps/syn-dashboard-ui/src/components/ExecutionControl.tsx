import { Loader2, Pause, Play, X } from 'lucide-react'
import { useState } from 'react'
import { useExecutionControl, type ExecutionState } from '../hooks'

interface ExecutionControlProps {
  executionId: string
  initialState?: ExecutionState
  className?: string
}

/**
 * Pause / Resume / Cancel buttons for a running or paused execution.
 * Uses HTTP endpoints — no WebSocket required.
 */
export function ExecutionControl({ executionId, initialState, className = '' }: ExecutionControlProps) {
  const {
    error,
    loading,
    pause,
    resume,
    cancel,
    canPause,
    canResume,
    canCancel,
  } = useExecutionControl(executionId, initialState)

  const [showCancelConfirm, setShowCancelConfirm] = useState(false)

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      {loading && <Loader2 className="h-4 w-4 animate-spin text-[var(--color-text-muted)]" />}

      {canPause && (
        <button
          onClick={() => pause()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium border border-yellow-500/30 bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/20 transition-colors disabled:opacity-50"
        >
          <Pause className="h-3.5 w-3.5" />
          Pause
        </button>
      )}

      {canResume && (
        <button
          onClick={() => resume()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-colors disabled:opacity-50"
        >
          <Play className="h-3.5 w-3.5" />
          Resume
        </button>
      )}

      {canCancel && (
        <>
          {showCancelConfirm ? (
            <div className="flex items-center gap-1">
              <button
                onClick={() => {
                  cancel('User cancelled from UI')
                  setShowCancelConfirm(false)
                }}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium border border-red-500/40 bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-colors"
              >
                Confirm cancel
              </button>
              <button
                onClick={() => setShowCancelConfirm(false)}
                className="inline-flex items-center px-2.5 py-1 rounded text-xs font-medium border border-[var(--color-border)] bg-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] transition-colors"
              >
                No
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowCancelConfirm(true)}
              disabled={loading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-50"
            >
              <X className="h-3.5 w-3.5" />
              Cancel
            </button>
          )}
        </>
      )}

      {error && (
        <span className="text-xs text-red-500">{error}</span>
      )}
    </div>
  )
}
