import { clsx } from 'clsx'
import {
  Activity,
  Play,
  Wrench,
  Zap,
} from 'lucide-react'
import { Link } from 'react-router-dom'

import { Card, CardContent, CardHeader, EmptyState, PageLoader, StatusBadge } from '../components'
import { useExecutionList } from '../hooks/useExecutionList'
import type { ExecutionListItem } from '../types'
import { formatDate, formatDurationFromRange } from '../utils/formatters'

function ExecutionProgressBar({ status, completed, total }: { status: string; completed: number; total: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-[var(--color-surface)] rounded-full overflow-hidden">
        <div
          className={clsx(
            'h-full rounded-full transition-all',
            status === 'completed' && 'bg-emerald-500',
            status === 'failed' && 'bg-red-500',
            status === 'running' && 'bg-blue-500',
            status === 'pending' && 'bg-slate-500'
          )}
          style={{ width: `${total > 0 ? (completed / total) * 100 : 0}%` }}
        />
      </div>
      <span className="text-xs text-[var(--color-text-muted)]">{completed}/{total}</span>
    </div>
  )
}

function ReposCell({ repos }: { repos?: string[] }) {
  if (!repos || repos.length === 0) return <div />
  if (repos.length === 1) {
    const name = repos[0].split('/').pop()?.replace(/\.git$/, '') ?? repos[0]
    return <div className="text-xs text-[var(--color-text-secondary)] truncate" title={repos[0]}>{name}</div>
  }
  return <div className="text-xs text-[var(--color-text-muted)]">{repos.length} repos</div>
}

function ExecutionListRow({ exec, now }: { exec: ExecutionListItem; now: number }) {
  return (
    <Link
      to={`/executions/${exec.workflow_execution_id}`}
      className="grid grid-cols-9 gap-4 px-4 py-4 hover:bg-[var(--color-surface-elevated)] transition-colors items-center"
    >
      <div className="font-mono text-sm text-[var(--color-text-primary)]">{exec.workflow_execution_id.slice(0, 8)}...</div>
      <div className="text-sm text-[var(--color-text-secondary)] truncate">{exec.workflow_name || exec.workflow_id.slice(0, 12)}</div>
      <div><StatusBadge status={exec.status} /></div>
      <ExecutionProgressBar status={exec.status} completed={exec.completed_phases} total={exec.total_phases} />
      <div className="text-sm text-[var(--color-text-secondary)] min-w-0">
        <span className="block truncate">{exec.total_tokens.toLocaleString()}</span>
        <span className="text-xs text-[var(--color-text-muted)]">(${Number(exec.total_cost_usd).toFixed(4)})</span>
      </div>
      <div className="text-sm text-[var(--color-text-secondary)]">{exec.tool_call_count}</div>
      <ReposCell repos={exec.repos} />
      <div className="text-sm text-[var(--color-text-secondary)]">{formatDurationFromRange(exec.started_at, exec.completed_at, now)}</div>
      <div className="text-xs text-[var(--color-text-muted)]">{formatDate(exec.started_at)}</div>
    </Link>
  )
}

function ExecutionTableHeader() {
  return (
    <div className="grid grid-cols-9 gap-4 px-4 py-3 text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wider bg-[var(--color-surface-elevated)]">
      <div>Execution ID</div>
      <div>Workflow</div>
      <div>Status</div>
      <div>Progress</div>
      <div className="flex items-center gap-1"><Zap className="h-3 w-3" />Tokens</div>
      <div className="flex items-center gap-1"><Wrench className="h-3 w-3" />Tools</div>
      <div>Repos</div>
      <div>Duration</div>
      <div>Started</div>
    </div>
  )
}

function Pagination({ page, setPage, pageSize, count }: {
  page: number
  setPage: React.Dispatch<React.SetStateAction<number>>
  pageSize: number
  count: number
}) {
  if (count < pageSize) return null
  return (
    <div className="flex justify-center gap-2">
      <button
        onClick={() => setPage((p) => Math.max(1, p - 1))}
        disabled={page === 1}
        className="px-3 py-1 text-sm rounded border border-[var(--color-border)] disabled:opacity-50"
      >
        Previous
      </button>
      <span className="px-3 py-1 text-sm text-[var(--color-text-secondary)]">Page {page}</span>
      <button
        onClick={() => setPage((p) => p + 1)}
        className="px-3 py-1 text-sm rounded border border-[var(--color-border)]"
      >
        Next
      </button>
    </div>
  )
}

export function ExecutionList() {
  const { executions, loading, error, statusFilter, setStatusFilter, page, setPage, pageSize, hasRunning, now } = useExecutionList()

  if (loading && executions.length === 0) return <PageLoader />
  if (error) {
    return <Card><EmptyState icon={Activity} title="Error loading executions" description={error} /></Card>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Execution History</h1>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">All workflow executions across all workflows</p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className={clsx('h-2 w-2 rounded-full', hasRunning ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400')} />
          <span className="text-[var(--color-text-muted)]">{hasRunning ? 'Auto-refresh (5s)' : 'Idle'}</span>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
        >
          <option value="">All statuses</option>
          <option value="pending">Pending</option>
          <option value="running">Running</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      <Card>
        <CardHeader title={`${executions.length} Execution${executions.length !== 1 ? 's' : ''}`} subtitle="Click a row to view execution details" />
        <CardContent noPadding>
          {executions.length === 0 ? (
            <div className="p-8 text-center">
              <Play className="mx-auto h-8 w-8 text-[var(--color-text-muted)]" />
              <p className="mt-2 text-sm text-[var(--color-text-muted)]">No executions yet. Run a workflow to create one.</p>
            </div>
          ) : (
            <div className="divide-y divide-[var(--color-border)]">
              <ExecutionTableHeader />
              {executions.map((exec) => <ExecutionListRow key={exec.workflow_execution_id} exec={exec} now={now} />)}
            </div>
          )}
        </CardContent>
      </Card>

      <Pagination page={page} setPage={setPage} pageSize={pageSize} count={executions.length} />
    </div>
  )
}
