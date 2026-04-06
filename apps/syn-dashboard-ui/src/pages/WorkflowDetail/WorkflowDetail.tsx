import { useState } from 'react'
import {
  ArrowLeft,
  GitBranch,
} from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { Card, EmptyState, PageLoader } from '../../components'
import { useWorkflowData } from '../../hooks'
import type { WorkflowResponse } from '../../types'
import { PhaseMetricsChart } from './PhaseMetricsChart'
import { PhasePipeline } from './PhasePipeline'
import { PhasePromptEditor } from './PhasePromptEditor'
import { WorkflowArtifactsList } from './WorkflowArtifactsList'
import { WorkflowExecutionForm } from './WorkflowExecutionForm'
import { WorkflowMetrics } from './WorkflowMetrics'

const STATUS_COLORS: Record<string, string> = {
  completed: '#22c55e',
  failed: '#ef4444',
}
const DEFAULT_STATUS_COLOR = '#4D80FF'

function truncatePhaseName(name: string, maxLen: number = 15): string {
  return name.length > maxLen ? name.slice(0, maxLen - 3) + '...' : name
}

function buildPhaseChartData(phases: { phase_name: string; total_tokens: number; cost_usd: number; status: string }[]) {
  return phases.map((p) => ({
    name: truncatePhaseName(p.phase_name),
    tokens: p.total_tokens,
    cost: p.cost_usd,
    fill: STATUS_COLORS[p.status] ?? DEFAULT_STATUS_COLOR,
  }))
}

function WorkflowDetailHeader({ workflow, workflowId }: { workflow: WorkflowResponse; workflowId: string }) {
  return (
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
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500/20 to-blue-400/20">
            <GitBranch className="h-6 w-6 text-blue-400" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">
                {workflow.name}
              </h1>
              <span className="px-2 py-1 text-xs rounded-full bg-blue-500/20 text-blue-400 ring-1 ring-inset ring-blue-500/30">
                Template
              </span>
            </div>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
              {workflow.description || `${workflow.workflow_type} workflow`}
            </p>
            <div className="mt-2 flex items-center gap-4 text-xs text-[var(--color-text-muted)]">
              <span className="font-mono">{workflow.id}</span>
              <span>&bull;</span>
              <span>{workflow.classification}</span>
            </div>
          </div>
        </div>
        <WorkflowExecutionForm
          workflowId={workflowId}
          declarations={workflow.input_declarations ?? []}
        />
      </div>
    </div>
  )
}

export function WorkflowDetail() {
  const { workflowId } = useParams<{ workflowId: string }>()
  const navigate = useNavigate()
  const { workflow, metrics, artifacts, executions, loading, error, refetch } = useWorkflowData(workflowId)
  const [selectedPhaseId, setSelectedPhaseId] = useState<string | null>(null)

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

  const phaseChartData = buildPhaseChartData(metrics?.phases ?? [])
  const selectedPhase = selectedPhaseId
    ? workflow.phases.find((p) => p.phase_id === selectedPhaseId)
    : null

  function handlePhaseSelect(phaseId: string) {
    setSelectedPhaseId((prev) => (prev === phaseId ? null : phaseId))
  }

  return (
    <div className="space-y-6">
      <WorkflowDetailHeader workflow={workflow} workflowId={workflowId!} />

      <WorkflowMetrics
        workflow={workflow}
        metrics={metrics}
        artifacts={artifacts}
        executions={executions}
        workflowId={workflowId!}
      />

      <PhasePipeline
        phases={workflow.phases}
        phaseMetrics={metrics?.phases}
        selectedPhaseId={selectedPhaseId}
        onPhaseSelect={handlePhaseSelect}
      />

      {selectedPhase && (
        <PhasePromptEditor
          key={selectedPhase.phase_id}
          phase={selectedPhase}
          workflowId={workflowId!}
          onSaved={refetch}
        />
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <PhaseMetricsChart phaseChartData={phaseChartData} />
        <WorkflowArtifactsList artifacts={artifacts} workflowId={workflowId!} />
      </div>
    </div>
  )
}
