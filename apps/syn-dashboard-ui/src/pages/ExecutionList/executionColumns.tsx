/**
 * Column definitions for the Executions table.
 *
 * Each column is a `ColumnDef<ExecutionListItem, ExecutionSortKey>` consumed
 * by the generic ResourceTable. Cell rendering uses the API's `*_display`
 * fields so formatting stays a single source of truth on the server.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { clsx } from 'clsx'
import type { ColumnDef } from '../../components'
import { StatusBadge } from '../../components'
import type { ExecutionSortKey } from '../../hooks/useExecutionList'
import type { ExecutionListItem } from '../../types'
import { formatRelativeTime, formatTimestampLocale } from '../../utils/formatters'

const EM_DASH = '—'

function ProgressBar({ exec }: { exec: ExecutionListItem }) {
  const pct = exec.total_phases > 0 ? (exec.completed_phases / exec.total_phases) * 100 : 0
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-20 overflow-hidden rounded-full bg-[var(--color-surface-elevated)]">
        <div
          className={clsx(
            'h-full rounded-full transition-all',
            exec.status === 'completed' && 'bg-emerald-500',
            exec.status === 'failed' && 'bg-red-500',
            exec.status === 'running' && 'bg-blue-500',
            exec.status === 'pending' && 'bg-slate-500',
            exec.status === 'cancelled' && 'bg-slate-400',
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-[var(--color-text-muted)]">
        {exec.completed_phases}/{exec.total_phases}
      </span>
    </div>
  )
}

const STATUS: ColumnDef<ExecutionListItem, ExecutionSortKey> = {
  key: 'status',
  label: 'Status',
  align: 'left',
  sortKey: 'status',
  render: (e) => <StatusBadge status={e.status} size="sm" />,
}

const WORKFLOW: ColumnDef<ExecutionListItem, ExecutionSortKey> = {
  key: 'workflow',
  label: 'Workflow',
  align: 'left',
  sortKey: 'workflow',
  cellClassName: 'text-sm text-[var(--color-text-primary)]',
  render: (e) => e.workflow_name || e.workflow_id,
}

const PROGRESS: ColumnDef<ExecutionListItem, ExecutionSortKey> = {
  key: 'progress',
  label: 'Progress',
  align: 'left',
  sortKey: 'progress',
  render: (e) => <ProgressBar exec={e} />,
}

const REPOS: ColumnDef<ExecutionListItem, ExecutionSortKey> = {
  key: 'repos',
  label: 'Repos',
  align: 'left',
  sortKey: 'repos',
  cellClassName: 'text-xs text-[var(--color-text-secondary)]',
  cellTitle: (e) => e.repos.join('\n') || undefined,
  render: (e) => e.repos_display ?? EM_DASH,
}

const TOKENS: ColumnDef<ExecutionListItem, ExecutionSortKey> = {
  key: 'tokens',
  label: 'Tokens',
  align: 'right',
  sortKey: 'tokens',
  cellClassName: 'font-mono text-xs text-[var(--color-text-secondary)]',
  render: (e) => e.total_tokens_display,
}

const COST: ColumnDef<ExecutionListItem, ExecutionSortKey> = {
  key: 'cost',
  label: 'Cost',
  align: 'right',
  sortKey: 'cost',
  cellClassName: 'font-mono text-xs text-[var(--color-text-secondary)]',
  render: (e) => e.total_cost_display,
}

const DURATION: ColumnDef<ExecutionListItem, ExecutionSortKey> = {
  key: 'duration',
  label: 'Duration',
  align: 'right',
  sortKey: 'duration',
  cellClassName: 'font-mono text-xs text-[var(--color-text-secondary)]',
  render: (e) => e.duration_display,
}

const STARTED: ColumnDef<ExecutionListItem, ExecutionSortKey> = {
  key: 'started',
  label: 'Started',
  align: 'left',
  sortKey: 'started',
  cellClassName: 'text-xs text-[var(--color-text-secondary)]',
  cellTitle: (e) => formatTimestampLocale(e.started_at) ?? undefined,
  render: (e) => formatRelativeTime(e.started_at),
}

export const EXECUTION_COLUMNS: ColumnDef<ExecutionListItem, ExecutionSortKey>[] = [
  STATUS,
  WORKFLOW,
  PROGRESS,
  REPOS,
  TOKENS,
  COST,
  DURATION,
  STARTED,
]
