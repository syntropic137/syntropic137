import { clsx } from 'clsx'
import {
  Activity,
  Play,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { listAllExecutions } from '../api/client'
import { Card, CardContent, CardHeader, EmptyState, PageLoader, StatusBadge } from '../components'
import type { ExecutionListItem } from '../types'


export function ExecutionList() {
  const [executions, setExecutions] = useState<ExecutionListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [page, setPage] = useState(1)
  const pageSize = 50

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    listAllExecutions({
      status: statusFilter || undefined,
      page,
      page_size: pageSize,
    })
      .then((response) => {
        if (cancelled) return
        setExecutions(response.executions)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [statusFilter, page])

  const formatDuration = (startedAt: string | null, completedAt: string | null): string => {
    if (!startedAt) return '-'
    const start = new Date(startedAt)
    const end = completedAt ? new Date(completedAt) : new Date()
    const seconds = Math.floor((end.getTime() - start.getTime()) / 1000)
    if (seconds < 60) return `${seconds}s`
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}m ${remainingSeconds}s`
  }

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return '-'
    return new Date(dateStr).toLocaleString()
  }

  if (loading && executions.length === 0) return <PageLoader />

  if (error) {
    return (
      <Card>
        <EmptyState
          icon={Activity}
          title="Error loading executions"
          description={error}
        />
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">
            Execution History
          </h1>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            All workflow executions across all workflows
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4">
        <select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value)
            setPage(1)
          }}
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

      {/* Executions List */}
      <Card>
        <CardHeader
          title={`${executions.length} Execution${executions.length !== 1 ? 's' : ''}`}
          subtitle="Click a row to view execution details"
        />
        <CardContent noPadding>
          {executions.length === 0 ? (
            <div className="p-8 text-center">
              <Play className="mx-auto h-8 w-8 text-[var(--color-text-muted)]" />
              <p className="mt-2 text-sm text-[var(--color-text-muted)]">
                No executions yet. Run a workflow to create one.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-[var(--color-border)]">
              {/* Table Header */}
              <div className="grid grid-cols-7 gap-4 px-4 py-3 text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wider bg-[var(--color-surface-elevated)]">
                <div>Execution ID</div>
                <div>Workflow</div>
                <div>Status</div>
                <div>Progress</div>
                <div className="flex items-center gap-1">
                  <Zap className="h-3 w-3" />
                  Tokens
                </div>
                <div>Duration</div>
                <div>Started</div>
              </div>
              {/* Table Rows */}
              {executions.map((exec) => {
                return (
                  <Link
                    key={exec.execution_id}
                    to={`/executions/${exec.execution_id}`}
                    className="grid grid-cols-7 gap-4 px-4 py-4 hover:bg-[var(--color-surface-elevated)] transition-colors items-center"
                  >
                    <div className="font-mono text-sm text-[var(--color-text-primary)]">
                      {exec.execution_id.slice(0, 8)}...
                    </div>
                    <div className="text-sm text-[var(--color-text-secondary)] truncate">
                      <Link
                        to={`/workflows/${exec.workflow_id}`}
                        className="hover:text-[var(--color-accent)] hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {exec.workflow_name || exec.workflow_id.slice(0, 12)}
                      </Link>
                    </div>
                    <div>
                      <StatusBadge status={exec.status} />
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 bg-[var(--color-surface)] rounded-full overflow-hidden">
                        <div
                          className={clsx(
                            'h-full rounded-full transition-all',
                            exec.status === 'completed' && 'bg-emerald-500',
                            exec.status === 'failed' && 'bg-red-500',
                            exec.status === 'running' && 'bg-blue-500',
                            exec.status === 'pending' && 'bg-slate-500'
                          )}
                          style={{ width: `${exec.total_phases > 0 ? (exec.completed_phases / exec.total_phases) * 100 : 0}%` }}
                        />
                      </div>
                      <span className="text-xs text-[var(--color-text-muted)]">
                        {exec.completed_phases}/{exec.total_phases}
                      </span>
                    </div>
                    <div className="text-sm text-[var(--color-text-secondary)]">
                      {exec.total_tokens.toLocaleString()}
                      <span className="text-xs text-[var(--color-text-muted)] ml-1">
                        (${Number(exec.total_cost_usd).toFixed(4)})
                      </span>
                    </div>
                    <div className="text-sm text-[var(--color-text-secondary)]">
                      {formatDuration(exec.started_at, exec.completed_at)}
                    </div>
                    <div className="text-xs text-[var(--color-text-muted)]">
                      {formatDate(exec.started_at)}
                    </div>
                  </Link>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pagination placeholder - can be enhanced later */}
      {executions.length >= pageSize && (
        <div className="flex justify-center gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1 text-sm rounded border border-[var(--color-border)] disabled:opacity-50"
          >
            Previous
          </button>
          <span className="px-3 py-1 text-sm text-[var(--color-text-secondary)]">
            Page {page}
          </span>
          <button
            onClick={() => setPage((p) => p + 1)}
            className="px-3 py-1 text-sm rounded border border-[var(--color-border)]"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}

