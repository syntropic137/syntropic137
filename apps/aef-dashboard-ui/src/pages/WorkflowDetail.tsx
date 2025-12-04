import { clsx } from 'clsx'
import {
  ArrowLeft,
  CheckCircle2,
  Clock,
  FileText,
  GitBranch,
  Play,
  XCircle,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
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

import { executeWorkflow, getMetrics, getWorkflow, getWorkflowHistory, listArtifacts, listExecutions } from '../api/client'
import { Card, CardContent, CardHeader, EmptyState, MetricCard, PageLoader, StatusBadge } from '../components'
import type { ArtifactSummary, ExecutionHistoryResponse, MetricsResponse, WorkflowExecutionSummary, WorkflowResponse } from '../types'

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

export function WorkflowDetail() {
  const { workflowId } = useParams<{ workflowId: string }>()
  const navigate = useNavigate()
  const [workflow, setWorkflow] = useState<WorkflowResponse | null>(null)
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null)
  const [, setHistory] = useState<ExecutionHistoryResponse | null>(null)
  const [artifacts, setArtifacts] = useState<ArtifactSummary[]>([])
  const [executions, setExecutions] = useState<WorkflowExecutionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isExecuting, setIsExecuting] = useState(false)
  const [executionMessage, setExecutionMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!workflowId) return

    let cancelled = false
    Promise.all([
      getWorkflow(workflowId),
      getMetrics(workflowId),
      getWorkflowHistory(workflowId),
      listArtifacts({ workflow_id: workflowId }),
      listExecutions(workflowId),
    ])
      .then(([wf, met, hist, arts, execs]) => {
        if (cancelled) return
        setWorkflow(wf)
        setMetrics(met)
        setHistory(hist)
        setArtifacts(arts)
        setExecutions(execs)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [workflowId])

  const handleExecute = async () => {
    if (!workflowId || isExecuting) return

    setIsExecuting(true)
    setExecutionMessage(null)

    try {
      const response = await executeWorkflow(workflowId, {
        inputs: { topic: 'AI Agents' }, // Default input for demo
        provider: 'claude',
      })
      setExecutionMessage(`Started! Execution ID: ${response.execution_id.slice(0, 8)}...`)

      // Clear message after 5 seconds
      setTimeout(() => setExecutionMessage(null), 5000)
    } catch (err) {
      setExecutionMessage(`Error: ${err instanceof Error ? err.message : 'Failed to start'}`)
    } finally {
      setIsExecuting(false)
    }
  }

  if (loading) return <PageLoader />

  if (error || !workflow) {
    return (
      <Card>
        <EmptyState
          icon={GitBranch}
          title="Workflow not found"
          description={error || `Could not find workflow with ID: ${workflowId}`}
          action={{ label: 'Back to Workflows', onClick: () => navigate('/workflows') }}
        />
      </Card>
    )
  }

  // Prepare phase metrics chart data
  const phaseChartData = metrics?.phases.map((p) => ({
    name: p.phase_name.length > 15 ? p.phase_name.slice(0, 12) + '...' : p.phase_name,
    tokens: p.total_tokens,
    cost: p.cost_usd,
    fill: p.status === 'completed' ? '#22c55e' : p.status === 'failed' ? '#ef4444' : '#6366f1',
  })) ?? []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <Link
          to="/workflows"
          className="inline-flex items-center gap-1 text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Workflows
        </Link>
        <div className="mt-4 flex items-start justify-between">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500/20 to-purple-500/20">
              <GitBranch className="h-6 w-6 text-indigo-400" />
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">
                  {workflow.name}
                </h1>
                <StatusBadge status={workflow.status} size="lg" pulse />
              </div>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                {workflow.description || `${workflow.workflow_type} workflow`}
              </p>
              <div className="mt-2 flex items-center gap-4 text-xs text-[var(--color-text-muted)]">
                <span className="font-mono">{workflow.id}</span>
                <span>•</span>
                <span>{workflow.classification}</span>
              </div>
            </div>
          </div>

          {/* Run Workflow Button */}
          <div className="flex flex-col items-end gap-2">
            <button
              onClick={handleExecute}
              disabled={isExecuting}
              className={clsx(
                'inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all',
                isExecuting
                  ? 'bg-slate-600 text-slate-300 cursor-not-allowed'
                  : 'bg-gradient-to-r from-emerald-500 to-teal-500 text-white hover:from-emerald-600 hover:to-teal-600 shadow-lg shadow-emerald-500/25 hover:shadow-emerald-500/40'
              )}
            >
              <Play className={clsx('h-4 w-4', isExecuting && 'animate-pulse')} />
              {isExecuting ? 'Running...' : 'Run Workflow'}
            </button>
            {executionMessage && (
              <span className={clsx(
                'text-xs',
                executionMessage.startsWith('Error') ? 'text-red-400' : 'text-emerald-400'
              )}>
                {executionMessage}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <MetricCard
          title="Phases"
          value={workflow.phases.length}
          icon={GitBranch}
          color="accent"
          subtitle={`${metrics?.phases.filter(p => p.status === 'completed').length ?? 0} completed`}
        />
        <Link to={`/workflows/${workflowId}/runs`} className="block">
          <MetricCard
            title="Runs"
            value={executions.length}
            icon={Play}
            color="success"
            subtitle="View all →"
          />
        </Link>
        <MetricCard
          title="Sessions"
          value={metrics?.total_sessions ?? 0}
          icon={Play}
        />
        <MetricCard
          title="Total Tokens"
          value={metrics?.total_tokens.toLocaleString() ?? 0}
          icon={Zap}
          subtitle={`$${Number(metrics?.total_cost_usd ?? 0).toFixed(4)}`}
        />
        <MetricCard
          title="Artifacts"
          value={artifacts.length}
          icon={FileText}
          subtitle={`${((metrics?.total_artifact_bytes ?? 0) / 1024).toFixed(1)} KB`}
        />
      </div>

      {/* Phase visualization */}
      <Card>
        <CardHeader title="Phase Pipeline" subtitle="Workflow execution phases" />
        <CardContent>
          <div className="flex items-center gap-2 overflow-x-auto pb-2">
            {workflow.phases.map((phase, idx) => {
              const Icon = phaseStatusIcons[phase.status] ?? Clock
              const phaseMetric = metrics?.phases.find(p => p.phase_id === phase.phase_id)

              return (
                <div key={phase.phase_id} className="flex items-center">
                  <div
                    className={clsx(
                      'flex min-w-[180px] flex-col rounded-lg border p-4 transition-all',
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
                    {phase.description && (
                      <p className="mt-1 text-xs text-[var(--color-text-secondary)] line-clamp-2">
                        {phase.description}
                      </p>
                    )}
                    {phaseMetric && (
                      <div className="mt-2 flex items-center gap-3 text-xs text-[var(--color-text-muted)]">
                        <span>{phaseMetric.total_tokens.toLocaleString()} tok</span>
                        <span>${Number(phaseMetric.cost_usd).toFixed(4)}</span>
                      </div>
                    )}
                  </div>
                  {idx < workflow.phases.length - 1 && (
                    <div className="mx-2 h-px w-8 bg-[var(--color-border)]" />
                  )}
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Token usage by phase */}
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

        {/* Artifacts list */}
        <Card>
          <CardHeader
            title="Artifacts"
            subtitle="Generated outputs"
            action={
              artifacts.length > 0 && (
                <Link
                  to={`/artifacts?workflow_id=${workflowId}`}
                  className="text-xs text-[var(--color-accent)] hover:underline"
                >
                  View all →
                </Link>
              )
            }
          />
          <CardContent noPadding>
            {artifacts.length === 0 ? (
              <div className="p-8 text-center">
                <FileText className="mx-auto h-8 w-8 text-[var(--color-text-muted)]" />
                <p className="mt-2 text-sm text-[var(--color-text-muted)]">
                  No artifacts generated yet
                </p>
              </div>
            ) : (
              <div className="divide-y divide-[var(--color-border)]">
                {artifacts.slice(0, 5).map((artifact) => (
                  <Link
                    key={artifact.id}
                    to={`/artifacts/${artifact.id}`}
                    className="flex items-center justify-between px-4 py-3 hover:bg-[var(--color-surface-elevated)] transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <FileText className="h-4 w-4 text-[var(--color-text-secondary)]" />
                      <div>
                        <p className="text-sm font-medium text-[var(--color-text-primary)]">
                          {artifact.title || artifact.id.slice(0, 12)}
                        </p>
                        <p className="text-xs text-[var(--color-text-muted)]">
                          {artifact.artifact_type} • {(artifact.size_bytes / 1024).toFixed(1)} KB
                        </p>
                      </div>
                    </div>
                    <span className="text-xs text-[var(--color-text-muted)]">
                      {artifact.phase_id}
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
