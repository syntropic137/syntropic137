import { Activity, ChevronDown, ChevronRight, Clipboard, Check } from 'lucide-react'
import { forwardRef, useCallback, useState } from 'react'
import { Card, CardContent, CardHeader } from '../../components'
import type { OperationInfo } from '../../types'
import { OperationTimelineItem } from './OperationTimelineItem'

function formatOperationText(op: OperationInfo): string {
  const parts: string[] = []
  const label = op.tool_name ?? op.operation_type
  parts.push(`[${op.timestamp}] ${label} (${op.operation_type})`)
  if (op.tool_input) parts.push(`Input: ${JSON.stringify(op.tool_input, null, 2)}`)
  if (op.tool_output) parts.push(`Output: ${op.tool_output}`)
  if (op.message_content) parts.push(`Message (${op.message_role}): ${op.message_content}`)
  if (op.thinking_content) parts.push(`Thinking: ${op.thinking_content}`)
  return parts.join('\n')
}

interface OperationTimelineProps {
  operations: OperationInfo[]
}

export const OperationTimeline = forwardRef<HTMLDivElement, OperationTimelineProps>(
  function OperationTimeline({ operations }, ref) {
    const [expandedSet, setExpandedSet] = useState<Set<string>>(new Set())
    const [copied, setCopied] = useState(false)

    const allExpanded = operations.length > 0 &&
      operations.every(op => expandedSet.has(op.operation_id))

    const toggleAll = useCallback(() => {
      if (allExpanded) {
        setExpandedSet(new Set())
      } else {
        setExpandedSet(new Set(operations.map(op => op.operation_id)))
      }
    }, [allExpanded, operations])

    const toggleOne = useCallback((id: string) => {
      setExpandedSet(prev => {
        const next = new Set(prev)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
      })
    }, [])

    const copyAll = useCallback(async () => {
      const text = [...operations].reverse()
        .map(formatOperationText)
        .join('\n\n---\n\n')
      await navigator.clipboard.writeText(text).catch(() => {/* clipboard unavailable */})
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }, [operations])

    const headerAction = operations.length > 0 ? (
      <div className="flex items-center gap-2">
        <button
          onClick={copyAll}
          className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-surface-elevated)] hover:text-[var(--color-text-secondary)] transition-colors"
          title="Copy all operations to clipboard"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Clipboard className="h-3.5 w-3.5" />}
          {copied ? 'Copied' : 'Copy All'}
        </button>
        <button
          onClick={toggleAll}
          className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-surface-elevated)] hover:text-[var(--color-text-secondary)] transition-colors"
        >
          {allExpanded ? (
            <><ChevronDown className="h-3.5 w-3.5" /> Collapse All</>
          ) : (
            <><ChevronRight className="h-3.5 w-3.5" /> Expand All</>
          )}
        </button>
      </div>
    ) : undefined

    return (
      <Card>
        <CardHeader
          title="Operations Timeline"
          subtitle={`${operations.length} operations recorded`}
          action={headerAction}
        />
        <CardContent noPadding>
          {operations.length === 0 ? (
            <div className="p-8 text-center">
              <Activity className="mx-auto h-8 w-8 text-[var(--color-text-muted)]" />
              <p className="mt-2 text-sm text-[var(--color-text-muted)]">
                No operations recorded yet
              </p>
            </div>
          ) : (
            <div ref={ref} className="relative">
              <div className="absolute left-8 top-0 bottom-0 w-px bg-[var(--color-border)]" />
              <div className="space-y-0">
                {[...operations].reverse().map((op, idx) => (
                  <OperationTimelineItem
                    key={op.operation_id}
                    op={op}
                    index={idx}
                    expanded={expandedSet.has(op.operation_id)}
                    onToggle={() => toggleOne(op.operation_id)}
                  />
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    )
  },
)
