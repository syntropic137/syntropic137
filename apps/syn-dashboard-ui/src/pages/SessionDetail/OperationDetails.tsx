import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import type { OperationInfo } from '../../types'

function DetailBlock({ label, content, mono = false, maxHeight = true }: {
  label: string
  content: string
  mono?: boolean
  maxHeight?: boolean
}) {
  return (
    <div className="mb-2">
      <span className="font-medium text-[var(--color-text-secondary)]">{label}</span>
      <pre className={`mt-1 ${maxHeight ? 'max-h-48' : ''} overflow-auto whitespace-pre-wrap text-[var(--color-text-muted)] ${mono ? 'font-mono' : ''}`}>
        {content}
      </pre>
    </div>
  )
}

function ExpandedDetails({ op }: { op: OperationInfo }) {
  return (
    <div className="mt-2 rounded-lg bg-[var(--color-surface)] p-3 text-xs">
      {op.tool_input && <DetailBlock label="Input:" content={JSON.stringify(op.tool_input, null, 2)} mono maxHeight={false} />}
      {op.tool_output && <DetailBlock label="Output:" content={op.tool_output} mono />}
      {op.message_content && <DetailBlock label={`Message (${op.message_role}):`} content={op.message_content} />}
      {op.thinking_content && <DetailBlock label="Thinking:" content={op.thinking_content} />}
    </div>
  )
}

export function OperationDetails({ op }: { op: OperationInfo }) {
  const [expanded, setExpanded] = useState(false)

  const hasDetails = op.tool_output || op.tool_input || op.message_content || op.thinking_content

  if (!hasDetails) return null

  const Icon = expanded ? ChevronDown : ChevronRight

  return (
    <div className="mt-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
      >
        <Icon className="h-3 w-3" />
        {expanded ? 'Hide details' : 'Show details'}
      </button>
      {expanded && <ExpandedDetails op={op} />}
    </div>
  )
}
