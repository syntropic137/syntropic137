import type { CaptureStatusResponse } from '../../api/capture'

/** One phase whose workspace ran with capture switched off (#1516). */
export interface DegradedPhase {
  /** null when the verdict was recorded without a phase. */
  phaseId: string | null
  /** The server's text, naming the failed checks. */
  display: string
}

/**
 * The phases of an execution whose workspace started with capture degraded,
 * ONE per phase however many rows say so.
 *
 * Two sources, because they exist at different times: the start-up verdict
 * (`capabilities`) is recorded as the agent launches, the teardown capture
 * verdict (`entries`) only once the phase ends. The start-up one names the
 * cause, so it wins when both exist. A ready start, no store configured and a
 * verdict that could not be read all yield nothing.
 */
export function degradedPhases(response: CaptureStatusResponse): DegradedPhase[] {
  const byPhase = new Map<string | null, DegradedPhase>()
  for (const capability of response.capabilities ?? []) {
    if (capability.status === 'ready') continue
    const phaseId = capability.phase_id ?? null
    if (!byPhase.has(phaseId)) byPhase.set(phaseId, { phaseId, display: capability.capability_status_display })
  }
  for (const entry of response.entries ?? []) {
    if (entry.state !== 'degraded') continue
    const phaseId = entry.phase_id ?? null
    if (!byPhase.has(phaseId)) byPhase.set(phaseId, { phaseId, display: entry.capture_status_display })
  }
  return [...byPhase.values()]
}
