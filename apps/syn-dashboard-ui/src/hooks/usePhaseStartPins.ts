import { useEffect, useState } from 'react'
import { getExecution } from '../api/executions'
import type { ExecutionDetailResponse, PhaseStartConfig, StartPinsStatus } from '../types'

/** How long to wait before asking again while the answer is still unknown. */
const RETRY_MS = 3000
/** Retries are bounded: a phase that never appears stops costing requests. */
const MAX_ATTEMPTS = 20

export interface PhaseStartPinsAnswer {
  pins: PhaseStartConfig | null
  status: StartPinsStatus
}

/** The answer for the given session's phase, or `undefined` if the phase is not listed yet. */
function answerFor(
  execution: ExecutionDetailResponse,
  sessionId: string,
): PhaseStartPinsAnswer | undefined {
  const phase = execution.phases.find((p) => p.session_id === sessionId)
  if (!phase) return undefined
  return { pins: phase.pinned_at_start ?? null, status: phase.start_pins_status ?? 'unavailable' }
}

/**
 * Ask until the server gives an answer (`recorded` or `not_recorded`), the
 * signal aborts, or MAX_ATTEMPTS is reached. Returns the pending-timer cleanup.
 */
function askUntilAnswered(
  ask: () => Promise<PhaseStartPinsAnswer | undefined>,
  onAnswer: (answer: PhaseStartPinsAnswer) => void,
  signal: AbortSignal,
  retryMs: number,
): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined
  let attempts = 0
  const attempt = async () => {
    attempts += 1
    // A failed request is not an answer either: stay unknown and retry.
    const answer = await ask().catch(() => undefined)
    if (signal.aborted) return
    if (answer) onAnswer(answer)
    const settled = answer !== undefined && answer.status !== 'unavailable'
    if (!settled && attempts < MAX_ATTEMPTS) timer = setTimeout(() => void attempt(), retryMs)
  }
  void attempt()
  return () => clearTimeout(timer)
}

/**
 * What the phase that ran the given session had at start (#1454), for a session page.
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
    const stop = askUntilAnswered(
      () => getExecution(executionId, controller.signal).then((e) => answerFor(e, sessionId)),
      (found) => setAnswer({ sessionId, ...found }),
      controller.signal,
      retryMs,
    )
    return () => {
      controller.abort()
      stop()
    }
  }, [executionId, sessionId, retryMs])

  return answer && answer.sessionId === sessionId
    ? { pins: answer.pins, status: answer.status }
    : undefined
}
