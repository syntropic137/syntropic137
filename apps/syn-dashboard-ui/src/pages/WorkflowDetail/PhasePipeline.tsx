import { clsx } from 'clsx'
import { GitBranch } from 'lucide-react'

import { Card, CardContent, CardHeader } from '../../components'
import type { PhaseDefinition, PhaseMetrics } from '../../types'
import { defaultPhaseStyle } from './workflowConstants'

interface PhasePipelineProps {
  phases: PhaseDefinition[]
  phaseMetrics: PhaseMetrics[] | undefined
}

function PhaseCard({ phase, phaseMetric }: { phase: PhaseDefinition; phaseMetric?: PhaseMetrics }) {
  return (
    <div
      className={clsx(
        'flex min-w-[180px] flex-col rounded-lg border p-4 transition-all',
        defaultPhaseStyle
      )}
    >
      <div className="flex items-center gap-2">
        <GitBranch className="h-4 w-4 text-slate-400" />
        <span className="text-sm font-medium text-[var(--color-text-primary)]">
          {phase.name}
        </span>
      </div>
      {phase.description && (
        <p className="mt-1 text-xs text-[var(--color-text-secondary)] line-clamp-2">
          {phase.description}
        </p>
      )}
      <div className="mt-2 text-xs text-[var(--color-text-muted)]">
        {phase.agent_type}
      </div>
      {phaseMetric && (
        <div className="mt-1 flex items-center gap-3 text-xs text-[var(--color-text-muted)]">
          <span>{phaseMetric.total_tokens.toLocaleString()} tok</span>
          <span>${Number(phaseMetric.cost_usd).toFixed(4)}</span>
        </div>
      )}
    </div>
  )
}

export function PhasePipeline({ phases, phaseMetrics }: PhasePipelineProps) {
  return (
    <Card>
      <CardHeader title="Phase Pipeline" subtitle="Workflow execution phases" />
      <CardContent>
        <div className="flex items-center gap-2 overflow-x-auto pb-2">
          {phases.map((phase, idx) => {
            const phaseMetric = phaseMetrics?.find(p => p.phase_id === phase.phase_id)
            return (
              <div key={phase.phase_id} className="flex items-center">
                <PhaseCard phase={phase} phaseMetric={phaseMetric} />
                {idx < phases.length - 1 && (
                  <div className="mx-2 h-px w-8 bg-[var(--color-border)]" />
                )}
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
