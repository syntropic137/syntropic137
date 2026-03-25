import { clsx } from 'clsx'
import { CheckCircle2, FileText, Play, XCircle, Zap } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'

import { Breadcrumbs, Card, EmptyState, MetricCard, PageLoader, StatusBadge } from '../../components'
import type { BreadcrumbItem } from '../../components/Breadcrumbs'
import { ExecutionControl } from '../../components/ExecutionControl'
import { useExecutionData } from '../../hooks'
import type { ExecutionDetailResponse } from '../../types'
import { formatDurationFromRange } from '../../utils/formatters'
import { ArtifactSection } from './ArtifactSection'
import { PhaseTimeline } from './PhaseTimeline'
import { TokenBreakdownChart } from './TokenBreakdownChart'

function ConnectionIndicator({ isConnected }: { isConnected: boolean }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={clsx('h-2 w-2 rounded-full', isConnected ? 'bg-emerald-500' : 'bg-slate-400')} />
      <span className="text-[var(--color-text-muted)]">{isConnected ? 'Live' : 'Connecting...'}</span>
    </div>
  )
}

function ExecutionErrorCard({ message }: { message: string }) {
  return (
    <Card>
      <div className="flex items-start gap-3 p-4 rounded-lg bg-red-500/10 border border-red-500/30">
        <XCircle className="h-5 w-5 text-red-400 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-medium text-red-400">Execution Failed</p>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">{message}</p>
        </div>
      </div>
    </Card>
  )
}

const CONTROLLABLE_STATUSES = new Set(['running', 'paused'])

function ExecutionHeader({ execution, executionId, isConnected, now, refreshExecution }: {
  execution: ExecutionDetailResponse
  executionId: string | undefined
  isConnected: boolean
  now: number
  refreshExecution: () => void
}) {
  const showControl = !!executionId && CONTROLLABLE_STATUSES.has(execution.status)
  return (
    <div className="flex justify-between items-start">
      <div>
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20">
            <Play className="h-6 w-6 text-emerald-400" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Execution</h1>
              <StatusBadge status={execution.status} size="lg" pulse={execution.status === 'running'} />
            </div>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">{execution.workflow_name}</p>
            <div className="mt-2 flex items-center gap-4 text-xs text-[var(--color-text-muted)]">
              <span className="font-mono">{execution.workflow_execution_id}</span>
              <span>&bull;</span>
              <span>Duration: {formatDurationFromRange(execution.started_at, execution.completed_at, now)}</span>
            </div>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-4">
        {showControl && (
          <ExecutionControl
            executionId={executionId}
            initialState={execution.status as 'running' | 'paused'}
            onSuccess={refreshExecution}
          />
        )}
        <ConnectionIndicator isConnected={isConnected} />
      </div>
    </div>
  )
}

function ExecutionMetricsGrid({ execution }: { execution: ExecutionDetailResponse }) {
  const totalTokens = execution.total_input_tokens + execution.total_output_tokens
  const completedPhases = execution.phases.filter(p => p.status === 'completed').length
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <MetricCard title="Phases" value={`${completedPhases}/${execution.phases.length}`} icon={CheckCircle2} color="success" subtitle={`${completedPhases} completed`} />
      <MetricCard title="Total Tokens" value={totalTokens.toLocaleString()} icon={Zap} subtitle={`In: ${execution.total_input_tokens.toLocaleString()} / Out: ${execution.total_output_tokens.toLocaleString()}`} />
      <MetricCard title="Total Cost" value={`$${Number(execution.total_cost_usd).toFixed(4)}`} icon={Zap} color="warning" />
      <MetricCard title="Artifacts" value={execution.artifact_ids.length} icon={FileText} color="accent" href="/artifacts" />
    </div>
  )
}

export function ExecutionDetail() {
  const { executionId } = useParams<{ executionId: string }>()
  const navigate = useNavigate()
  const { execution, artifactDetails, loading, error, isConnected, now, refreshExecution } =
    useExecutionData(executionId)

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

  const breadcrumbs: BreadcrumbItem[] = [
    { label: execution.workflow_name || execution.workflow_id, href: `/workflows/${execution.workflow_id}` },
    { label: `Execution ${execution.workflow_execution_id.slice(0, 8)}` },
  ]

  return (
    <div className="space-y-6">
      <Breadcrumbs items={breadcrumbs} />
      <ExecutionHeader execution={execution} executionId={executionId} isConnected={isConnected} now={now} refreshExecution={refreshExecution} />
      {execution.error_message && <ExecutionErrorCard message={execution.error_message} />}
      <ExecutionMetricsGrid execution={execution} />
      <PhaseTimeline phases={execution.phases} now={now} />
      {execution.artifact_ids.length > 0 && (
        <ArtifactSection phases={execution.phases} artifactDetails={artifactDetails} />
      )}
      <TokenBreakdownChart inputTokens={execution.total_input_tokens} outputTokens={execution.total_output_tokens} />
    </div>
  )
}
