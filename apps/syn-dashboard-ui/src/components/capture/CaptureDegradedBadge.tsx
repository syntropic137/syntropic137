import { AlertTriangle } from 'lucide-react'
import { useEffect, useState } from 'react'

import { type CaptureStatusEntry, getExecutionCaptureStatus } from '../../api/capture'

/**
 * The verdicts of an execution whose workspace started with capture switched
 * off (#1516). A healthy store, no store at all, and a verdict that could not
 * be read all yield nothing: only a recorded degraded start is shown.
 */
function degradedCaptures(entries: readonly CaptureStatusEntry[]): CaptureStatusEntry[] {
  return entries.filter((entry) => entry.state === 'degraded')
}

/**
 * "Capture degraded" on an execution, naming the failed check and, when the
 * run had several phases, which ones. Renders nothing otherwise, including
 * when the capture status cannot be fetched: this is telemetry about the run,
 * never a reason to break its page.
 */
export function CaptureDegradedBadge({ executionId }: { executionId: string }) {
  const [degraded, setDegraded] = useState<CaptureStatusEntry[]>([])

  useEffect(() => {
    const controller = new AbortController()
    getExecutionCaptureStatus(executionId, controller.signal)
      .then((response) => setDegraded(degradedCaptures(response.entries ?? [])))
      .catch(() => setDegraded([]))
    return () => controller.abort()
  }, [executionId])

  const [first] = degraded
  if (!first) return null
  const phases = degraded.map((entry) => entry.phase_id).filter((id): id is string => Boolean(id))
  const title = degraded.map((entry) => `${entry.phase_id ?? 'phase'}: ${entry.capture_status_display}`).join('\n')
  return (
    <span
      data-testid="capture-degraded-badge"
      title={title}
      className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-xs font-medium text-amber-400"
    >
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>{first.capture_status_display}</span>
      {phases.length > 1 && <span className="text-amber-400/80">({phases.length} phases)</span>}
    </span>
  )
}
