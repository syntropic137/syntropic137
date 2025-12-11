import { clsx } from 'clsx'
import {
  CheckCircle2,
  Clock,
  FileText,
  Play,
  XCircle,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { getExecution } from '../api/client'
import { Breadcrumbs, Card, CardContent, CardHeader, EmptyState, MetricCard, PageLoader, StatusBadge } from '../components'
import type { BreadcrumbItem } from '../components/Breadcrumbs'
import { useExecutionStream } from '../hooks'
import type { ExecutionDetailResponse } from '../types'

const phaseStatusIcons: Record<string, typeof Play> = {
  pending: Clock,
  running: Play,
  completed: CheckCircle2,
  failed: XCircle,
}

const phaseStatusColors: Record<string, string> = {
  pending: 'border-slate-500/30 bg-slate-500/10',
  running: 'border-blue-500/30 bg-blue-500/10',
  completed: 'border-emerald-500/30 bg-emerald-500/10',
  failed: 'border-red-500/30 bg-red-500/10',
}

export function ExecutionDetail() {
  const { executionId } = useParams<{ executionId: string }>()
  const navigate = useNavigate()
  const [execution, setExecution] = useState<ExecutionDetailResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())

  // Refresh execution data
  const refreshExecution = useCallback(() => {
    if (!executionId) return
    getExecution(executionId)
      .then((exec) => setExecution(exec))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [executionId])

  // Initial data fetch
  useEffect(() => {
    refreshExecution()
  }, [refreshExecution])

  // WebSocket subscription for live updates
  const { isConnected } = useExecutionStream(executionId, {
    onEvent: (event) => {
      // Refresh on relevant domain events
      if (event.type === 'event' && event.event_type) {
        const refreshEvents = [
          'PhaseStarted',
          'PhaseCompleted',
          'WorkflowCompleted',
          'WorkflowFailed',
          'OperationRecorded',
        ]
        if (refreshEvents.includes(event.event_type)) {
          refreshExecution()
        }
      }
    },
  })

  // Timer for live duration updates (only depends on status to avoid resetting)
  useEffect(() => {
    if (!execution || execution.status !== 'running') return

    const interval = setInterval(() => {
      setNow(Date.now())
    }, 1000)

    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Intentionally only depend on status to avoid timer reset
  }, [execution?.status])

  if (loading) return <PageLoader />

  if (error || !execution) {
    return (
      <Card>
        <EmptyState
          icon={Play}
          title="Execution not found"
          description={error || `Could not find execution with ID: ${executionId}`}
          action={{ label: 'Back to Workflows', onClick: () => navigate('/workflows') }}
        />
      </Card>
    )
  }

  const formatDuration = (startedAt: string | null, completedAt: string | null): string => {
    if (!startedAt) return '-'
    const start = new Date(startedAt)
    // Use `now` state for running executions to enable live timer updates
    const end = completedAt ? new Date(completedAt) : new Date(now)
    const seconds = Math.floor((end.getTime() - start.getTime()) / 1000)
    if (seconds < 60) return `${seconds}s`
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}m ${remainingSeconds}s`
  }

  const totalTokens = execution.total_input_tokens + execution.total_output_tokens
  const completedPhases = execution.phases.filter(p => p.status === 'completed').length

  // Prepare phase metrics chart data
  const phaseChartData = execution.phases.map((p) => ({
    name: p.name.length > 15 ? p.name.slice(0, 12) + '...' : p.name,
    tokens: p.input_tokens + p.output_tokens,
    cost: p.cost_usd,
    fill: p.status === 'completed' ? '#22c55e' : p.status === 'failed' ? '#ef4444' : '#6366f1',
  }))

  // Build breadcrumb trail: Workflow → Execution
  const breadcrumbs: BreadcrumbItem[] = [
    {
      label: execution.workflow_name || execution.workflow_id,
      href: `/workflows/${execution.workflow_id}`,
    },
    {
      label: `Execution ${execution.execution_id.slice(0, 8)}`,
    },
  ]

  return (
    <div className="space-y-6">
      {/* Breadcrumbs */}
      <Breadcrumbs items={breadcrumbs} />

      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20">
              <Play className="h-6 w-6 text-emerald-400" />
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">
                  Execution
                </h1>
                <StatusBadge status={execution.status} size="lg" pulse={execution.status === 'running'} />
              </div>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                {execution.workflow_name}
              </p>
              <div className="mt-2 flex items-center gap-4 text-xs text-[var(--color-text-muted)]">
                <span className="font-mono">{execution.execution_id}</span>
                <span>•</span>
                <span>Duration: {formatDuration(execution.started_at, execution.completed_at)}</span>
              </div>
            </div>
          </div>
        </div>
        {/* Connection status indicator */}
        <div className="flex items-center gap-2 text-sm">
          <span
            className={clsx(
              'h-2 w-2 rounded-full',
              isConnected ? 'bg-emerald-500' : 'bg-slate-400'
            )}
          />
          <span className="text-[var(--color-text-muted)]">
            {isConnected ? 'Live' : 'Connecting...'}
          </span>
        </div>
      </div>

      {/* Error Message */}
      {execution.error_message && (
        <Card>
          <CardContent>
            <div className="flex items-start gap-3 p-4 rounded-lg bg-red-500/10 border border-red-500/30">
              <XCircle className="h-5 w-5 text-red-400 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-red-400">Execution Failed</p>
                <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                  {execution.error_message}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Metrics */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Phases"
          value={`${completedPhases}/${execution.phases.length}`}
          icon={CheckCircle2}
          color="success"
          subtitle={`${completedPhases} completed`}
        />
        <MetricCard
          title="Total Tokens"
          value={totalTokens.toLocaleString()}
          icon={Zap}
          subtitle={`In: ${execution.total_input_tokens.toLocaleString()} / Out: ${execution.total_output_tokens.toLocaleString()}`}
        />
        <MetricCard
          title="Total Cost"
          value={`$${Number(execution.total_cost_usd).toFixed(4)}`}
          icon={Zap}
          color="warning"
        />
        <MetricCard
          title="Artifacts"
          value={execution.artifact_ids.length}
          icon={FileText}
          color="accent"
          href="/artifacts"
        />
      </div>

      {/* Phase Pipeline */}
      <Card>
        <CardHeader title="Phase Pipeline" subtitle="Execution phases with per-phase metrics" />
        <CardContent>
          <div className="flex items-center gap-2 overflow-x-auto pb-2">
            {execution.phases.map((phase, idx) => {
              const Icon = phaseStatusIcons[phase.status] ?? Clock
              const phaseTokens = phase.input_tokens + phase.output_tokens

              return (
                <div key={phase.phase_id} className="flex items-center">
                  <div
                    className={clsx(
                      'flex min-w-[200px] flex-col rounded-lg border p-4 transition-all',
                      phaseStatusColors[phase.status] ?? phaseStatusColors.pending
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <Icon className={clsx(
                        'h-4 w-4',
                        phase.status === 'completed' && 'text-emerald-400',
                        phase.status === 'running' && 'text-blue-400',
                        phase.status === 'failed' && 'text-red-400',
                        phase.status === 'pending' && 'text-slate-400'
                      )} />
                      <span className="text-sm font-medium text-[var(--color-text-primary)]">
                        {phase.name}
                      </span>
                    </div>
                    <div className="mt-3 space-y-1 text-xs text-[var(--color-text-muted)]">
                      <div className="flex justify-between">
                        <span>Tokens:</span>
                        <span className="text-[var(--color-text-secondary)]">{phaseTokens.toLocaleString()}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Cost:</span>
                        <span className="text-[var(--color-text-secondary)]">${Number(phase.cost_usd).toFixed(4)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Duration:</span>
                        <span className="text-[var(--color-text-secondary)]">
                          {phase.status === 'running' && phase.started_at
                            ? `${((now - new Date(phase.started_at).getTime()) / 1000).toFixed(1)}s`
                            : `${phase.duration_seconds.toFixed(1)}s`
                          }
                        </span>
                      </div>
                    </div>
                    {phase.session_id && (
                      <Link
                        to={`/sessions/${phase.session_id}`}
                        className="mt-3 text-xs text-[var(--color-accent)] hover:underline"
                      >
                        View Session →
                      </Link>
                    )}
                  </div>
                  {idx < execution.phases.length - 1 && (
                    <div className="mx-2 h-px w-8 bg-[var(--color-border)]" />
                  )}
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Token Usage by Phase Chart */}
      <Card>
        <CardHeader title="Token Usage by Phase" subtitle="Tokens consumed per phase" />
        <CardContent className="h-[250px]">
          {phaseChartData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={phaseChartData} layout="vertical">
                <XAxis type="number" tick={{ fill: 'var(--color-text-muted)', fontSize: 11 }} />
                <YAxis
                  type="category"
                  dataKey="name"
                  tick={{ fill: 'var(--color-text-secondary)', fontSize: 11 }}
                  width={100}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'var(--color-surface-elevated)',
                    border: '1px solid var(--color-border)',
                    borderRadius: '8px',
                    fontSize: '12px',
                  }}
                  formatter={(value: number) => [value.toLocaleString(), 'tokens']}
                />
                <Bar dataKey="tokens" radius={[0, 4, 4, 0]}>
                  {phaseChartData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-[var(--color-text-muted)]">
              No phase metrics yet
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
