import { CheckCircle2, CircleDashed, SkipForward } from 'lucide-react'

import type { ExecutionDetailResponse } from '../../types'
import './PhasePlan.css'

type PlannedPhase = ExecutionDetailResponse['phase_plan'][number]

const icons: Record<string, typeof CircleDashed> = {
  inherited: CheckCircle2,
  skipped: SkipForward,
}

/**
 * A declared phase that did not run in THIS execution (feedback cee46909):
 * still to come, made unnecessary by a review, or completed by the run this
 * one resumed. There is no session, tokens or cost to show, so it presents the
 * server's words for where the phase stands and nothing it would have to work
 * out for itself.
 */
export function PlannedPhaseCard({ phase }: { phase: PlannedPhase }) {
  const Icon = icons[phase.status] ?? CircleDashed
  return (
    <div className={`phase-planned phase-planned--${phase.status}`} data-status={phase.status}>
      <div className="phase-planned__title">
        <Icon className="phase-planned__icon" aria-hidden="true" />
        <span className="phase-planned__name">{phase.name}</span>
      </div>
      <span className="phase-planned__status">{phase.status_display}</span>
    </div>
  )
}
