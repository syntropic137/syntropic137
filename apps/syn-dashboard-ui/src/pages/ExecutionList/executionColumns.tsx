/**
 * Column definitions for the Executions table.
 *
 * Each column is a `ColumnDef<ExecutionListItem, ExecutionSortKey>` consumed
 * by the generic ResourceTable. Cell rendering uses the API's `*_display`
 * fields so formatting stays a single source of truth on the server.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import type { ColumnDef } from '../../components'
import { StatusBadge } from '../../components'
import { ExecutionEvalBadge } from '../../components/evals'
import type { ExecutionSortKey } from '../../hooks/useExecutionList'
import type { ExecutionListItem } from '../../types'
import { formatRelativeTime, formatTimestampLocale } from '../../utils/formatters'
import { ExecutionProgressBar } from './ExecutionProgressBar'
import { queueLabel } from './queueLabel'

const EM_DASH = '—'

const STATUS: ColumnDef<ExecutionListItem, ExecutionSortKey> = {
  key: 'status',
  label: 'Status',
  align: 'left',
  sortKey: 'status',
  render: (e) => (
    <StatusBadge status={e.status} failureClassification={e.failure_classification} size="sm" />
  ),
}

const WORKFLOW: ColumnDef<ExecutionListItem, ExecutionSortKey> = {
  key: 'workflow',
  label: 'Workflow',
  align: 'left',
  sortKey: 'workflow',
  cellClassName: 'text-sm text-[var(--color-text-primary)]',
  // An eval run carries its badge under the name, so it reads apart from an
  // ordinary run at a glance; the width cap is what makes a long name truncate.
  render: (e) => (
    <div className="flex min-w-0 max-w-[18rem] flex-col items-start gap-1">
      <span>{e.workflow_name || e.workflow_id}</span>
      <ExecutionEvalBadge evalRun={e.eval} />
    </div>
  ),
}

const PROGRESS: ColumnDef<ExecutionListItem, ExecutionSortKey> = {
  key: 'progress',
  label: 'Progress',
  align: 'left',
  sortKey: 'progress',
  render: (e) => <ExecutionProgressBar exec={e} />,
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
  cellTitle: (e) =>
    e.start_queue ? queueLabel(e.start_queue) : (formatTimestampLocale(e.started_at) ?? undefined),
  render: (e) => (e.start_queue ? queueLabel(e.start_queue) : formatRelativeTime(e.started_at)),
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
