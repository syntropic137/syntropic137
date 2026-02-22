import { Loader2, X } from 'lucide-react'
import { useState } from 'react'
import { useExecutionControl, type ExecutionState } from '../hooks'

interface ExecutionControlProps {
  executionId: string
  initialState?: ExecutionState
  /** Called after a successful command so the parent can refresh execution data */
  onSuccess?: () => void
  className?: string
}

/**
 * Cancel button for a running execution.
 * Shows a confirmation step before sending the cancel signal.
 * While the backend processes the cancel the button is replaced with a
 * "Cancelling…" indicator so the UI never flickers back to the cancel button.
 */
export function ExecutionControl({ executionId, initialState, onSuccess, className = '' }: ExecutionControlProps) {
  const { error, loading, cancel, canCancel, state } = useExecutionControl(
    executionId,
    initialState,
    onSuccess
  )

  const [showCancelConfirm, setShowCancelConfirm] = useState(false)

  if (state === 'cancelling') {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <Loader2 className="h-4 w-4 animate-spin text-[var(--color-text-muted)]" />
        <span className="text-sm text-[var(--color-text-muted)]">Cancelling…</span>
      </div>
    )
  }

  if (!canCancel) return null

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      {loading && <Loader2 className="h-4 w-4 animate-spin text-[var(--color-text-muted)]" />}

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

      {error && <span className="text-xs text-red-500">{error}</span>}
    </div>
  )
}
