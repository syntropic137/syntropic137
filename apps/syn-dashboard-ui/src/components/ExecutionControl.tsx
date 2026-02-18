import { Pause, Play, X } from 'lucide-react'
import { useState } from 'react'
import { useExecutionControl, type ExecutionState } from '../hooks'

interface ExecutionControlProps {
  executionId: string
  className?: string
}

/**
 * Execution state indicator with background color.
 */
function StateIndicator({ state }: { state: ExecutionState }) {
  const stateStyles: Record<ExecutionState, { bg: string; text: string; label: string }> = {
    pending: { bg: 'bg-gray-100', text: 'text-gray-700', label: 'Pending' },
    running: { bg: 'bg-blue-100', text: 'text-blue-700', label: 'Running' },
    paused: { bg: 'bg-yellow-100', text: 'text-yellow-700', label: 'Paused' },
    cancelled: { bg: 'bg-orange-100', text: 'text-orange-700', label: 'Cancelled' },
    completed: { bg: 'bg-green-100', text: 'text-green-700', label: 'Completed' },
    failed: { bg: 'bg-red-100', text: 'text-red-700', label: 'Failed' },
    unknown: { bg: 'bg-gray-100', text: 'text-gray-500', label: 'Unknown' },
  }

  const style = stateStyles[state] || stateStyles.unknown

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${style.bg} ${style.text}`}>
      {state === 'running' && (
        <span className="mr-1.5 h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
      )}
      {state === 'paused' && (
        <span className="mr-1.5 h-2 w-2 rounded-full bg-yellow-500" />
      )}
      {style.label}
    </span>
  )
}

/**
 * Control buttons for execution management.
 */
export function ExecutionControl({ executionId, className = '' }: ExecutionControlProps) {
  const {
    state,
    connected,
    error,
    pause,
    resume,
    cancel,
    canPause,
    canResume,
    canCancel,
  } = useExecutionControl(executionId)

  const [showCancelConfirm, setShowCancelConfirm] = useState(false)

  return (
    <div className={`flex items-center gap-3 ${className}`}>
      {/* State indicator */}
      <StateIndicator state={state} />

      {/* Connection status */}
      {!connected && (
        <span className="text-xs text-gray-400">
          (Disconnected)
        </span>
      )}

      {/* Control buttons */}
      <div className="flex items-center gap-2">
        {canPause && (
          <button
            onClick={() => pause()}
            className="inline-flex items-center px-3 py-1.5 border border-yellow-300 text-sm font-medium rounded-md text-yellow-700 bg-yellow-50 hover:bg-yellow-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-yellow-500"
          >
            <Pause className="mr-1.5 h-4 w-4" />
            Pause
          </button>
        )}

        {canResume && (
          <button
            onClick={() => resume()}
            className="inline-flex items-center px-3 py-1.5 border border-green-300 text-sm font-medium rounded-md text-green-700 bg-green-50 hover:bg-green-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500"
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
                className="inline-flex items-center px-3 py-1.5 border border-red-300 text-sm font-medium rounded-md text-red-700 bg-red-50 hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
              >
                <X className="mr-1.5 h-4 w-4" />
                Cancel
              </button>
            )}
          </>
        )}
      </div>

      {/* Error display */}
      {error && (
        <span className="text-xs text-red-500">
          {error}
        </span>
      )}
    </div>
  )
}

/**
 * Standalone state indicator component for use in lists.
 */
export function ExecutionStateIndicator({ executionId }: { executionId: string }) {
  const { state, connected } = useExecutionControl(executionId)

  return (
    <div className="flex items-center gap-1">
      <StateIndicator state={state} />
      {!connected && (
        <span className="h-1.5 w-1.5 rounded-full bg-gray-300" title="Disconnected" />
      )}
    </div>
  )
}
