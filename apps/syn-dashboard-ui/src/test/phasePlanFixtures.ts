import type { ExecutionDetailResponse } from '../types'

type Phase = ExecutionDetailResponse['phases'][number]
type PlannedPhase = ExecutionDetailResponse['phase_plan'][number]

/**
 * The `phase_plan` the server returns for a run whose declared phases are
 * exactly the ones it started: each phase that ran, with its own status.
 *
 * For fixtures about the phases that ran. A test about phases that did NOT run
 * states its plan by hand (PhasePlan.test.tsx).
 */
export function planOf(phases: readonly Phase[]): PlannedPhase[] {
  return phases.map((p) => ({
    phase_id: p.workflow_phase_id,
    name: p.name,
    status: p.status,
    status_display: p.status,
  }))
}

/** ``execution`` with the plan of its own phases, unless it states one. */
export function withPlanOfPhases(execution: ExecutionDetailResponse): ExecutionDetailResponse {
  return { ...execution, phase_plan: execution.phase_plan ?? planOf(execution.phases) }
}
