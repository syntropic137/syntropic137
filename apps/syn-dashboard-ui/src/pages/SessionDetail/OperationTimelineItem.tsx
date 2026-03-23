import { clsx } from 'clsx'
import {
  Activity,
  CheckCircle2,
  XCircle,
} from 'lucide-react'
import type { OperationInfo } from '../../types'
import { formatTime } from '../../utils/formatters'
import { OperationDetails } from './OperationDetails'
import { OperationMetaBadges } from './OperationMetaBadges'
import { operationColors, operationIcons } from './sessionConstants'

function formatOperationLabel(op: OperationInfo): string {
  if (op.operation_type.startsWith('git_') && op.tool_name) {
    return `Git ${op.tool_name.charAt(0).toUpperCase()}${op.tool_name.slice(1)}`
  }
  return op.operation_type
    .split('_')
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

export function OperationTimelineItem({ op, index }: { op: OperationInfo; index: number }) {
  const Icon = operationIcons[op.operation_type] ?? Activity
  const color = operationColors[op.operation_type] ?? 'text-[var(--color-text-secondary)] bg-[var(--color-surface-elevated)]'
  const [textColor, bgColor] = color.split(' ')

  return (
    <div
      className="relative flex items-start gap-4 px-4 py-3 hover:bg-[var(--color-surface-elevated)] transition-colors animate-fade-in"
      style={{ animationDelay: `${index * 30}ms` }}
    >
      <div className={clsx('relative z-10 flex h-8 w-8 items-center justify-center rounded-lg', bgColor)}>
        <Icon className={clsx('h-4 w-4', textColor)} />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-[var(--color-text-primary)]">
            {formatOperationLabel(op)}
          </span>
          {op.success ? (
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
          ) : (
            <XCircle className="h-3.5 w-3.5 text-red-400" />
          )}
          <span className="text-xs text-[var(--color-text-muted)]">
            {formatTime(op.timestamp)}
          </span>
        </div>

        <OperationMetaBadges op={op} />
        <OperationDetails op={op} />
      </div>
    </div>
  )
}
