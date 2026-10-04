import { useEffect, useState } from 'react'
import { getExecution } from '../api/executions'
import type { PhaseStartConfig } from '../types'

/**
 * What the phase that ran `sessionId` had at start (#1454), for a session page.
 *
 * Fetched once: the pins are fixed when the execution starts, so polling them
 * would only re-read the same answer. The phase is found by its session id,
 * which is the one key both responses carry under the same name.
 *
 * THREE-VALUED. `undefined` is "we do not know" - still loading, no execution,
 * or the fetch failed - and renders nothing. `null` is the answer "not
 * recorded", and only the server can give it.
 */
export function usePhaseStartPins(
  executionId: string | null | undefined,
  sessionId: string | undefined,
): PhaseStartConfig | null | undefined {
  const [pins, setPins] = useState<PhaseStartConfig | null | undefined>(undefined)

  useEffect(() => {
    setPins(undefined)
    if (!executionId || !sessionId) return
    const controller = new AbortController()
    getExecution(executionId, controller.signal)
      .then((execution) => {
        const phase = execution.phases.find((p) => p.session_id === sessionId)
        // A session whose phase is not on the execution is unknown, not "not recorded".
        if (phase) setPins(phase.pinned_at_start ?? null)
      })
      .catch(() => {
        // Context for the header, never the page's own data: stay unknown.
      })
    return () => controller.abort()
  }, [executionId, sessionId])

  return pins
}
