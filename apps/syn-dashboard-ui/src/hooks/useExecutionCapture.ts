/**
 * Which phases of an execution ran with capture degraded (#1516), kept fresh
 * for as long as the execution page is open.
 *
 * The verdict can arrive at any point in the run - at an agent's launch, or
 * at its phase's teardown - so a single read on mount misses every verdict
 * recorded after it. This polls through `useSerialRefresh` while the run is
 * live and reads once more whenever its status changes, which is what catches
 * the teardown verdict of a run that has just finished.
 */

import { useCallback, useEffect, useState } from 'react'

import { getExecutionCaptureStatus } from '../api/capture'
import { type DegradedPhase, degradedPhases } from '../components/capture/degradedPhases'
import { isTerminalExecutionStatus } from '../utils/terminalStatus'
import { RUNNING_POLL_INTERVAL_MS, useSerialRefresh } from './useSerialRefresh'

export function useExecutionCapture(executionId: string, status: string): DegradedPhase[] {
  const [degraded, setDegraded] = useState<DegradedPhase[]>([])

  // Another execution's verdicts must never be shown on this one's page.
  useEffect(() => setDegraded([]), [executionId])

  const fetchCapture = useCallback(
    (signal: AbortSignal): Promise<void> =>
      // No id yet (the page is still loading its execution): nothing to ask.
      !executionId
        ? Promise.resolve()
        : getExecutionCaptureStatus(executionId, signal)
            .then((response) => {
              if (!signal.aborted) setDegraded(degradedPhases(response))
            })
            // Telemetry about the run, never a reason to break its page; a
            // failed refresh keeps what is already on screen.
            .catch(() => undefined),
    [executionId],
  )

  const { refetch } = useSerialRefresh({
    fetch: fetchCapture,
    pollIntervalMs: isTerminalExecutionStatus(status) ? null : RUNNING_POLL_INTERVAL_MS,
  })

  // On mount, on a new execution, and on every status change - the last one
  // is the terminal refresh that picks up a finished phase's verdict.
  useEffect(() => {
    refetch()
  }, [refetch, fetchCapture, status])

  return degraded
}
