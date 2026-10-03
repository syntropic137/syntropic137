import { CheckCircle2, Clock, OctagonX, Play, ShieldAlert, XCircle } from 'lucide-react'

import { REFUSED, TASK_FAILED } from '../../utils/executionOutcome'

/*
 * Keyed by OUTCOME TONE rather than by status, which for every phase but one
 * is the same string. The exception is the phase that reported
 * `success=false` on a run the server classified `correct_refusal`: it gets
 * the amber `refused` entries below, because it is the phase that did the
 * refusing and drawing it in the same red as a crash says the opposite of
 * what happened (#1367). `outcomeTone` decides which; these only say how it
 * looks.
 */
export const phaseStatusIcons: Record<string, typeof Play> = {
  pending: Clock,
  running: Play,
  completed: CheckCircle2,
  failed: XCircle,
  // Not `XCircle`: an icon that means "something went wrong" is the same
  // claim as the red, made again in a form colour-blind operators can read.
  [REFUSED]: ShieldAlert,
  // Same icon, same claim: this phase ended on its own report, not on a crash.
  [TASK_FAILED]: ShieldAlert,
  interrupted: OctagonX,
  cancelled: OctagonX,
}

export const phaseStatusColors: Record<string, string> = {
  pending: 'border-slate-500/30 bg-slate-500/10',
  running: 'border-blue-500/30 bg-blue-500/10',
  completed: 'border-emerald-500/30 bg-emerald-500/10',
  failed: 'border-red-500/30 bg-red-500/10',
  [REFUSED]: 'border-amber-500/30 bg-amber-500/10',
  [TASK_FAILED]: 'border-amber-500/30 bg-amber-500/10',
  interrupted: 'border-orange-500/30 bg-orange-500/10',
  cancelled: 'border-amber-500/30 bg-amber-500/10',
}
