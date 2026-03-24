import { XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'

import { getConversationLog } from '../../api/observability'
import type { ConversationLogResponse } from '../../api/observability'
import { ConversationLogLine } from './ConversationLogLine'
import { LogErrorState, LogLoadingState, ModalOverlay } from './ConversationLogStates'

export function ConversationLogViewer({
  sessionId,
  onClose,
}: {
  sessionId: string
  onClose: () => void
}) {
  const [log, setLog] = useState<ConversationLogResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedLines, setExpandedLines] = useState<Set<number>>(new Set())
  const [copiedLine, setCopiedLine] = useState<number | null>(null)

  const copyToClipboard = async (text: string, lineNumber: number) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedLine(lineNumber)
      setTimeout(() => setCopiedLine(null), 2000)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  useEffect(() => {
    getConversationLog(sessionId, { limit: 500 })
      .then(setLog)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [sessionId])

  const toggleLine = (lineNumber: number) => {
    setExpandedLines((prev) => {
      const next = new Set(prev)
      if (next.has(lineNumber)) next.delete(lineNumber)
      else next.add(lineNumber)
      return next
    })
  }

  if (loading) return <LogLoadingState />
  if (error || !log || log.lines.length === 0) return <LogErrorState error={error} onClose={onClose} />

  return (
    <ModalOverlay>
      <div className="flex h-[90vh] w-full max-w-5xl flex-col rounded-xl bg-[var(--color-surface)] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">Conversation Log</h2>
            <p className="text-sm text-[var(--color-text-muted)]">
              {log.total_lines} lines &bull; Session: {sessionId.slice(0, 8)}...
            </p>
          </div>
          <button onClick={onClose} className="rounded-lg p-2 hover:bg-[var(--color-surface-elevated)]">
            <XCircle className="h-5 w-5 text-[var(--color-text-muted)]" />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4">
          <div className="space-y-2">
            {log.lines.map((line) => (
              <ConversationLogLine
                key={line.line_number}
                line={line}
                isExpanded={expandedLines.has(line.line_number)}
                copiedLine={copiedLine}
                onToggle={toggleLine}
                onCopy={copyToClipboard}
              />
            ))}
          </div>
        </div>
      </div>
    </ModalOverlay>
  )
}
