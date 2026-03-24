import { clsx } from 'clsx'
import { CheckCircle2, ChevronDown, ChevronRight, Copy, Wrench } from 'lucide-react'

import type { ConversationLogResponse } from '../../api/observability'
import { conversationEventColors } from './sessionConstants'

type LogLine = ConversationLogResponse['lines'][number]

function tryFormatJson(raw: string, parsed: Record<string, unknown> | null): string {
  if (parsed) return JSON.stringify(parsed, null, 2)
  try { return JSON.stringify(JSON.parse(raw), null, 2) } catch { return raw }
}

function CopyButton({
  line,
  copiedLine,
  onCopy,
}: {
  line: LogLine
  copiedLine: number | null
  onCopy: (text: string, lineNumber: number) => void
}) {
  const isCopied = copiedLine === line.line_number

  return (
    <button
      onClick={(e) => {
        e.stopPropagation()
        onCopy(tryFormatJson(line.raw, line.parsed), line.line_number)
      }}
      className={clsx(
        'flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors',
        isCopied
          ? 'bg-emerald-500/20 text-emerald-400'
          : 'bg-[var(--color-surface)] text-[var(--color-text-muted)] hover:bg-[var(--color-accent)] hover:text-white',
      )}
    >
      {isCopied ? (
        <>
          <CheckCircle2 className="h-3.5 w-3.5" />
          Copied!
        </>
      ) : (
        <>
          <Copy className="h-3.5 w-3.5" />
          Copy
        </>
      )}
    </button>
  )
}

export function ConversationLogLine({
  line,
  isExpanded,
  copiedLine,
  onToggle,
  onCopy,
}: {
  line: LogLine
  isExpanded: boolean
  copiedLine: number | null
  onToggle: (lineNumber: number) => void
  onCopy: (text: string, lineNumber: number) => void
}) {
  const colorClass =
    conversationEventColors[line.event_type || ''] ||
    'text-[var(--color-text-secondary)] bg-[var(--color-surface-elevated)]'
  const [textColor, bgColor] = colorClass.split(' ')

  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-elevated)]">
      <button
        onClick={() => onToggle(line.line_number)}
        className="flex w-full items-center gap-3 px-4 py-2 text-left hover:bg-[var(--color-surface)]"
      >
        <span className="font-mono text-xs text-[var(--color-text-muted)] w-8">
          {line.line_number + 1}
        </span>
        <span className={clsx('rounded px-2 py-0.5 text-xs font-medium', bgColor, textColor)}>
          {line.event_type || 'unknown'}
        </span>
        {line.tool_name && (
          <span className="flex items-center gap-1 text-xs text-amber-400">
            <Wrench className="h-3 w-3" />
            {line.tool_name}
          </span>
        )}
        {line.content_preview && (
          <span className="flex-1 truncate text-xs text-[var(--color-text-muted)]">
            {line.content_preview}
          </span>
        )}
        {isExpanded ? (
          <ChevronDown className="h-4 w-4 text-[var(--color-text-muted)]" />
        ) : (
          <ChevronRight className="h-4 w-4 text-[var(--color-text-muted)]" />
        )}
      </button>

      {isExpanded && (
        <div className="border-t border-[var(--color-border)] p-4">
          <div className="flex justify-end mb-2">
            <CopyButton line={line} copiedLine={copiedLine} onCopy={onCopy} />
          </div>
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap font-mono text-xs text-[var(--color-text-secondary)]">
            {tryFormatJson(line.raw, line.parsed)}
          </pre>
        </div>
      )}
    </div>
  )
}
