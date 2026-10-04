import { useEffect, useState } from 'react'
import { getExecution } from '../api/executions'
import type { PhaseStartConfig, StartPinsStatus } from '../types'

/** How long to wait before asking again while the answer is still unknown. */
const RETRY_MS = 3000
/** Retries are bounded: a phase that never appears stops costing requests. */
const MAX_ATTEMPTS = 20

export interface PhaseStartPinsAnswer {
  pins: PhaseStartConfig | null
  status: StartPinsStatus
}

/**
 * What the phase that ran `sessionId` had at start (#1454), for a session page.
 *
 * The pins are fixed when the execution starts, so once the server has
 * answered `recorded` or `not_recorded` nothing is asked again. Until then it
 * retries, for as long as the page is mounted and at most MAX_ATTEMPTS times:
 * a session can be open before the execution projection lists its phase, a
 * request can fail, and the server can report the start event `unavailable`.
 * None of those is an answer, and the header must not freeze on them.
 *
 * `undefined` is "we do not know" - still loading, no execution, the phase is
 * not listed yet, or the request failed - and renders nothing.
 */
export function usePhaseStartPins(
  executionId: string | null | undefined,
  sessionId: string | undefined,
  retryMs: number = RETRY_MS,
): PhaseStartPinsAnswer | undefined {
  // Tagged with the session it answers for, so a stale answer reads as unknown
  // after navigating to another session instead of describing the wrong phase.
  const [answer, setAnswer] = useState<{ sessionId: string } & PhaseStartPinsAnswer>()

  useEffect(() => {
    if (!executionId || !sessionId) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let attempts = 0

    const ask = () => {
      attempts += 1
      getExecution(executionId, controller.signal)
        .then((execution) => {
          const phase = execution.phases.find((p) => p.session_id === sessionId)
          // A session whose phase is not on the execution yet is unknown, not "not recorded".
          if (!phase) return false
          const status = phase.start_pins_status ?? 'unavailable'
          setAnswer({ sessionId, pins: phase.pinned_at_start ?? null, status })
          return status !== 'unavailable'
        })
        // Context for the header, never the page's own data: stay unknown and retry.
        .catch(() => false)
        .then((resolved) => {
          if (!resolved && !controller.signal.aborted && attempts < MAX_ATTEMPTS) {
            timer = setTimeout(ask, retryMs)
          }
        })
    }
    ask()
    return () => {
      controller.abort()
      if (timer) clearTimeout(timer)
    }
  }, [executionId, sessionId, retryMs])

  return answer && answer.sessionId === sessionId
    ? { pins: answer.pins, status: answer.status }
    : undefined
}
