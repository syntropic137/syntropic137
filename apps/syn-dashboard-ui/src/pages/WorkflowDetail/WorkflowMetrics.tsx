import { FileText, GitBranch, Play, Zap } from 'lucide-react'
import { Link } from 'react-router-dom'

import { MetricCard } from '../../components'
import type { ArtifactSummary, MetricsResponse, WorkflowExecutionSummary, WorkflowResponse } from '../../types'

interface WorkflowMetricsProps {
  workflow: WorkflowResponse
  metrics: MetricsResponse | null
  artifacts: ArtifactSummary[]
  executions: WorkflowExecutionSummary[]
  workflowId: string
}

export function WorkflowMetrics({ workflow, metrics, artifacts, executions, workflowId }: WorkflowMetricsProps) {
  return (
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
          subtitle="View all \u2192"
        />
      </Link>
      <MetricCard title="Sessions" value={metrics?.total_sessions ?? 0} icon={Play} />
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
  )
}
