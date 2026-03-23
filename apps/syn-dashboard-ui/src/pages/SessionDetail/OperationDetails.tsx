import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import type { OperationInfo } from '../../types'

export function OperationDetails({ op }: { op: OperationInfo }) {
  const [expanded, setExpanded] = useState(false)

  const hasDetails = op.tool_output || op.tool_input || op.message_content || op.thinking_content

  if (!hasDetails) return null

  return (
    <div className="mt-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {expanded ? 'Hide details' : 'Show details'}
      </button>
      {expanded && (
        <div className="mt-2 rounded-lg bg-[var(--color-surface)] p-3 text-xs">
          {op.tool_input && (
            <div className="mb-2">
              <span className="font-medium text-[var(--color-text-secondary)]">Input:</span>
              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-[var(--color-text-muted)] font-mono">
                {JSON.stringify(op.tool_input, null, 2)}
              </pre>
            </div>
          )}
          {op.tool_output && (
            <div className="mb-2">
              <span className="font-medium text-[var(--color-text-secondary)]">Output:</span>
              <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap text-[var(--color-text-muted)] font-mono">
                {op.tool_output}
              </pre>
            </div>
          )}
          {op.message_content && (
            <div className="mb-2">
              <span className="font-medium text-[var(--color-text-secondary)]">
                Message ({op.message_role}):
              </span>
              <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap text-[var(--color-text-muted)]">
                {op.message_content}
              </pre>
            </div>
          )}
          {op.thinking_content && (
            <div>
              <span className="font-medium text-[var(--color-text-secondary)]">Thinking:</span>
              <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap text-[var(--color-text-muted)]">
                {op.thinking_content}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
