import { clsx } from 'clsx'
import {
  Activity,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Users,
  Wrench,
  XCircle,
} from 'lucide-react'
import type { OperationInfo } from '../../types'
import { formatTime } from '../../utils/formatters'
import { OperationDetails } from './OperationDetails'
import { OperationMetaBadges } from './OperationMetaBadges'
import { operationColors, operationIcons } from './sessionConstants'

function formatStatusLabel(operationType: string): string {
  return operationType
    .split('_')
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

function getPrimaryLabel(op: OperationInfo): string {
  if (op.tool_name) {
    if (op.operation_type.startsWith('git_')) {
      return `Git ${op.tool_name.charAt(0).toUpperCase()}${op.tool_name.slice(1)}`
    }
    return op.tool_name
  }
  return formatStatusLabel(op.operation_type)
}

function truncate(text: string, max = 140): string {
  return text.length > max ? text.slice(0, max) + '...' : text
}

function getGitPreview(op: OperationInfo): string | null {
  if (!op.operation_type.startsWith('git_')) return null
  const parts: string[] = []
  if (op.git_sha) parts.push(op.git_sha.slice(0, 7))
  if (op.git_message) parts.push(op.git_message.split('\n')[0])
  if (op.git_branch) parts.push(`on ${op.git_branch}`)
  return parts.length > 0 ? parts.join(' ') : null
}

function getPreview(op: OperationInfo): string | null {
  const gitPreview = getGitPreview(op)
  if (gitPreview) return truncate(gitPreview)
  if (op.tool_input) return truncate(JSON.stringify(op.tool_input))
  if (op.tool_output) return truncate(op.tool_output.split('\n')[0])
  if (op.message_content) return truncate(op.message_content.split('\n')[0])
  return null
}

function ExpandToggle({ expanded, preview, onToggle }: {
  expanded: boolean
  preview: string | null
  onToggle: () => void
}) {
  const Chevron = expanded ? ChevronDown : ChevronRight

  function getLabel() {
    if (expanded) return <span className="text-[var(--color-text-muted)] group-hover:text-[var(--color-text-secondary)]">Hide details</span>
    if (preview) {
      return (
        <span className="font-mono truncate rounded bg-[var(--color-background)] border border-[var(--color-border)] px-2 py-0.5 text-[var(--color-text-muted)] group-hover:text-[var(--color-text-secondary)] group-hover:border-[var(--color-text-muted)]/30 transition-colors">
          {preview}
        </span>
      )
    }
    return <span className="text-[var(--color-text-muted)] group-hover:text-[var(--color-text-secondary)]">Show details</span>
  }

  return (
    <button
      onClick={onToggle}
      className="mt-1.5 flex items-center gap-1.5 w-full text-left text-xs cursor-pointer group"
    >
      <Chevron className="h-3 w-3 shrink-0 text-[var(--color-text-muted)]" />
      {getLabel()}
    </button>
  )
}

const SUBAGENT_TYPES = new Set(['subagent_started', 'subagent_stopped'])
const DEFAULT_COLOR = 'text-[var(--color-text-secondary)] bg-[var(--color-surface-elevated)]'

function deriveOpProps(op: OperationInfo) {
  const Icon = operationIcons[op.operation_type] ?? Activity
  const color = operationColors[op.operation_type] ?? DEFAULT_COLOR
  const [textColor, bgColor] = color.split(' ')
  const hasGitDetails = !!op.git_message
  const hasDetails = !!(op.tool_output || op.tool_input || op.message_content || op.thinking_content || hasGitDetails)
  const showToolIcon = !!op.tool_name && !op.operation_type.startsWith('git_')
  const ToolIcon = SUBAGENT_TYPES.has(op.operation_type) ? Users : Wrench
  const StatusIcon = op.success ? CheckCircle2 : XCircle
  const statusColor = op.success ? 'text-emerald-400' : 'text-red-400'
  return { Icon, textColor, bgColor, hasDetails, showToolIcon, ToolIcon, StatusIcon, statusColor }
}

export function OperationTimelineItem({ op, index, expanded, onToggle }: {
  op: OperationInfo
  index: number
  expanded: boolean
  onToggle: () => void
}) {
  const { Icon, textColor, bgColor, hasDetails, showToolIcon, ToolIcon, StatusIcon, statusColor } = deriveOpProps(op)
  const preview = getPreview(op)

  return (
    <div
      className="relative flex items-start py-2 hover:bg-[var(--color-surface-elevated)]/50 transition-colors animate-fade-in"
      style={{ animationDelay: `${index * 30}ms` }}
    >
      <div className="flex w-[52px] shrink-0 items-start justify-center pt-0.5">
        <div className={clsx('relative z-10 flex h-8 w-8 items-center justify-center rounded-lg', bgColor)}>
          <Icon className={clsx('h-4 w-4', textColor)} />
        </div>
      </div>

      <div className="flex-1 min-w-0 pl-4 pr-4">
        <div className="flex items-center gap-2">
          {showToolIcon && <ToolIcon className="h-3.5 w-3.5 text-[var(--color-text-secondary)]" />}
          <span className="text-sm font-semibold text-[var(--color-text-primary)]">
            {getPrimaryLabel(op)}
          </span>
          <span className="text-xs text-[var(--color-text-muted)]">
            ({formatStatusLabel(op.operation_type)})
          </span>
          <StatusIcon className={clsx('h-3 w-3', statusColor)} />
          <span className="text-xs text-[var(--color-text-muted)] ml-auto shrink-0">
            {formatTime(op.timestamp)}
          </span>
        </div>

        <OperationMetaBadges op={op} />

        {hasDetails && <ExpandToggle expanded={expanded} preview={preview} onToggle={onToggle} />}
        {expanded && hasDetails && <OperationDetails op={op} />}
      </div>
    </div>
  )
}
