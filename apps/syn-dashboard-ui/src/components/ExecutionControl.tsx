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
          className="inline-flex items-center px-3 py-1.5 border border-yellow-300 text-sm font-medium rounded-md text-yellow-700 bg-yellow-50 hover:bg-yellow-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-yellow-500 disabled:opacity-50"
        >
          <Pause className="mr-1.5 h-4 w-4" />
          Pause
        </button>
      )}

      {canResume && (
        <button
          onClick={() => resume()}
          disabled={loading}
          className="inline-flex items-center px-3 py-1.5 border border-green-300 text-sm font-medium rounded-md text-green-700 bg-green-50 hover:bg-green-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 disabled:opacity-50"
        >
          <Play className="mr-1.5 h-4 w-4" />
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
                className="inline-flex items-center px-2 py-1 border border-red-300 text-xs font-medium rounded text-red-700 bg-red-50 hover:bg-red-100"
              >
                Confirm
              </button>
              <button
                onClick={() => setShowCancelConfirm(false)}
                className="inline-flex items-center px-2 py-1 border border-gray-300 text-xs font-medium rounded text-gray-600 bg-white hover:bg-gray-50"
              >
                No
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowCancelConfirm(true)}
              disabled={loading}
              className="inline-flex items-center px-3 py-1.5 border border-red-300 text-sm font-medium rounded-md text-red-700 bg-red-50 hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 disabled:opacity-50"
            >
              <X className="mr-1.5 h-4 w-4" />
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
