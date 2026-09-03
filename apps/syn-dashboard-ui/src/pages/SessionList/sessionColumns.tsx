/**
 * Column definitions for the Sessions table.
 *
 * Each column is a `ColumnDef<SessionSummary, SortKey>` consumed by the
 * generic ResourceTable. Cell rendering uses the API's `*_display` fields
 * directly so formatting stays a single source of truth on the server.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import type { ColumnDef } from '../../components'
import type { SortKey } from '../../hooks/useSortUrlState'
import type { SessionSummary } from '../../types'
import { AgentBadge, StatusBadge } from '../../components'
import { formatRelativeTime, formatTimestampLocale } from '../../utils/formatters'

const EM_DASH = '—'

const STATUS: ColumnDef<SessionSummary, SortKey> = {
  key: 'status',
  label: 'Status',
  align: 'left',
  sortKey: 'status',
  render: (s) => <StatusBadge status={s.status} size="sm" />,
}

const AGENT: ColumnDef<SessionSummary, SortKey> = {
  key: 'agent',
  label: 'Agent',
  align: 'left',
  // Provider AND model: a sessions list that shows only the harness cannot
  // answer "did this run on the model I asked for" (issue #1094). Tooltip
  // carries the raw model id the badge renders compactly.
  cellTitle: (s) => [s.agent_provider, s.agent_model].filter(Boolean).join(' / ') || undefined,
  render: (s) =>
    s.agent_provider || s.agent_model_display ? (
      <AgentBadge provider={s.agent_provider} modelDisplay={s.agent_model_display} />
    ) : (
      EM_DASH
    ),
}

const WORKFLOW: ColumnDef<SessionSummary, SortKey> = {
  key: 'workflow',
  label: 'Workflow',
  align: 'left',
  sortKey: 'workflow',
  cellClassName: 'text-sm text-[var(--color-text-primary)]',
  render: (s) => s.workflow_name ?? s.workflow_id ?? 'Unknown workflow',
}

const PHASE: ColumnDef<SessionSummary, SortKey> = {
  key: 'phase',
  label: 'Phase',
  align: 'left',
  sortKey: 'phase',
  cellClassName: 'text-xs text-[var(--color-text-secondary)]',
  cellTitle: (s) => s.phase_id ?? undefined,
  render: (s) => s.phase_display ?? s.phase_id ?? EM_DASH,
}

const REPOS: ColumnDef<SessionSummary, SortKey> = {
  key: 'repos',
  label: 'Repos',
  align: 'left',
  sortKey: 'repos',
  cellClassName: 'text-xs text-[var(--color-text-secondary)]',
  cellTitle: (s) => s.repos.join('\n') || undefined,
  render: (s) => s.repos_display ?? EM_DASH,
}

const TOKENS: ColumnDef<SessionSummary, SortKey> = {
  key: 'tokens',
  label: 'Tokens',
  align: 'right',
  sortKey: 'tokens',
  cellClassName: 'font-mono text-xs text-[var(--color-text-secondary)]',
  render: (s) => s.total_tokens_display,
}

const COST: ColumnDef<SessionSummary, SortKey> = {
  key: 'cost',
  label: 'Cost',
  align: 'right',
  sortKey: 'cost',
  cellClassName: 'font-mono text-xs text-[var(--color-text-secondary)]',
  render: (s) => s.total_cost_display,
}

const DURATION: ColumnDef<SessionSummary, SortKey> = {
  key: 'duration',
  label: 'Duration',
  align: 'right',
  sortKey: 'duration',
  cellClassName: 'font-mono text-xs text-[var(--color-text-secondary)]',
  render: (s) => s.duration_display,
}

const STARTED: ColumnDef<SessionSummary, SortKey> = {
  key: 'started',
  label: 'Started',
  align: 'left',
  sortKey: 'started',
  cellClassName: 'text-xs text-[var(--color-text-secondary)]',
  cellTitle: (s) => formatTimestampLocale(s.started_at) ?? undefined,
  render: (s) => formatRelativeTime(s.started_at),
}

export const SESSION_COLUMNS: ColumnDef<SessionSummary, SortKey>[] = [
  STATUS,
  WORKFLOW,
  AGENT,
  PHASE,
  REPOS,
  TOKENS,
  COST,
  DURATION,
  STARTED,
]
