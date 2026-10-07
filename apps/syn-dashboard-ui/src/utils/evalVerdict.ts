/**
 * How a verdict looks, in one place: the pill, the sparkline and the timeline
 * all colour a verdict the same way, so a reader learns it once.
 *
 * Red is FAIL (the agent did not meet the goal). ERROR is amber, not red: the
 * scorer could not judge the run, which says nothing about the agent.
 */

import type { EvalRun, EvalVerdict } from '../api/evals'

export const VERDICT_COLOURS: Record<EvalVerdict, string> = {
  PASS: '#10b981',
  FAIL: '#ef4444',
  ERROR: '#f59e0b',
}

/** A run nobody has scored yet. */
export const UNSCORED_COLOUR = '#64748b'

export function verdictColour(verdict: EvalVerdict | null): string {
  return verdict ? VERDICT_COLOURS[verdict] : UNSCORED_COLOUR
}

/** The key that groups runs into the variants the API compares. */
export function variantKey(workflowId: string, models: readonly string[]): string {
  return `${workflowId} · ${models.length ? models.join(', ') : 'no model reported'}`
}

/** The variant a run belongs to: its workflow plus the sorted unique models its phases reported. */
export function runVariantKey(run: EvalRun): string {
  const models = [...new Set(run.models.map((m) => m.model))].sort()
  return variantKey(run.workflow_id, models)
}

/** A 0..1 score, which has no `*_display` field in the contract. */
export function formatScore(score: number | null): string {
  return score === null ? '—' : score.toFixed(2)
}
