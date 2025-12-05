import { clsx } from 'clsx'
import {
  ArrowLeft,
  Play,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { getWorkflow, listExecutions } from '../api/client'
import { Card, CardContent, CardHeader, EmptyState, PageLoader, StatusBadge } from '../components'
import type { WorkflowExecutionSummary, WorkflowResponse } from '../types'


export function WorkflowRuns() {
  const { workflowId } = useParams<{ workflowId: string }>()
  const navigate = useNavigate()
  const [workflow, setWorkflow] = useState<WorkflowResponse | null>(null)
  const [executions, setExecutions] = useState<WorkflowExecutionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!workflowId) return

    let cancelled = false
    Promise.all([
      getWorkflow(workflowId),
      listExecutions(workflowId),
    ])
      .then(([wf, execs]) => {
        if (cancelled) return
        setWorkflow(wf)
        setExecutions(execs)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [workflowId])

  if (loading) return <PageLoader />

  if (error || !workflow) {
    return (
      <Card>
        <EmptyState
          icon={Play}
          title="Workflow not found"
          description={error || `Could not find workflow with ID: ${workflowId}`}
          action={{ label: 'Back to Workflows', onClick: () => navigate('/workflows') }}
        />
      </Card>
    )
  }

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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <Link
          to={`/workflows/${workflowId}`}
          className="inline-flex items-center gap-1 text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to {workflow.name}
        </Link>
        <h1 className="mt-4 text-2xl font-bold text-[var(--color-text-primary)]">
          Execution Runs
        </h1>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
          All runs of {workflow.name}
        </p>
      </div>

      {/* Runs List */}
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
                No executions yet. Run the workflow to create one.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-[var(--color-border)]">
              {/* Table Header */}
              <div className="grid grid-cols-6 gap-4 px-4 py-3 text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wider bg-[var(--color-surface-elevated)]">
                <div>Execution ID</div>
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
                    className="grid grid-cols-6 gap-4 px-4 py-4 hover:bg-[var(--color-surface-elevated)] transition-colors items-center"
                  >
                    <div className="font-mono text-sm text-[var(--color-text-primary)]">
                      {exec.execution_id.slice(0, 8)}...
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
                          style={{ width: `${(exec.completed_phases / exec.total_phases) * 100}%` }}
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
    </div>
  )
}
