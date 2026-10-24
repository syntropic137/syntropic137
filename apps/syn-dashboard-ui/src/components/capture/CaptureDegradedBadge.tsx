import { AlertTriangle } from 'lucide-react'

import type { DegradedPhase } from './degradedPhases'

const BADGE_CLASSES =
  'inline-flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-xs font-medium text-amber-400'

/**
 * "Capture degraded" on an execution, naming the failed check and, when more
 * than one phase degraded, how many (#1516). Renders nothing for a run with
 * no degraded phase. Each affected phase also carries `CapturePhaseIndicator`.
 */
export function CaptureDegradedBadge({ degraded }: { degraded: readonly DegradedPhase[] }) {
  const [first] = degraded
  if (!first) return null
  const title = degraded.map((phase) => `${phase.phaseId ?? 'phase'}: ${phase.display}`).join('\n')
  return (
    <span data-testid="capture-degraded-badge" title={title} className={BADGE_CLASSES}>
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>{first.display}</span>
      {degraded.length > 1 && <span className="text-amber-400/80">({degraded.length} phases)</span>}
    </span>
  )
}

/**
 * The same verdict on the one phase it is about, as visible text rather than
 * a tooltip, so the failed check is readable on a touch screen too.
 */
export function CapturePhaseIndicator({ degraded }: { degraded: DegradedPhase | undefined }) {
  if (!degraded) return null
  return (
    <span data-testid="capture-phase-degraded" className={`${BADGE_CLASSES} mt-2 self-start`}>
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>{degraded.display}</span>
    </span>
  )
}
