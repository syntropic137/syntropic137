import { useEffect, useState } from 'react'
import { getExecution } from '../api/executions'
import type { ExecutionDetailResponse, PhaseSkillUse, PhaseStartConfig, StartPinsStatus } from '../types'
import { isTerminalExecutionStatus } from '../utils/terminalStatus'

/** How long to wait before asking again while the answer is still unknown. */
const RETRY_MS = 3000
/** Retries are bounded: a phase that never appears stops costing requests. */
const MAX_ATTEMPTS = 20
/**
 * How often to re-read skill use while the phase can still invoke skills.
 * Slower than RETRY_MS: this is a live view of a known phase, not a search.
 */
const LIVE_REFRESH_MS = 15000

export interface PhaseStartPinsAnswer {
  pins: PhaseStartConfig | null
  status: StartPinsStatus
  /** Which of those skills the agent invoked (#1269); absent from an older server. */
  skillUse?: PhaseSkillUse
}

/** An answer, and whether the phase can still change it. */
interface Reading {
  answer: PhaseStartPinsAnswer
  /** The phase is still running, so its skill use can still grow. */
  live: boolean
}

/** The reading for the given session's phase, or `undefined` if the phase is not listed yet. */
function readingFor(execution: ExecutionDetailResponse, sessionId: string): Reading | undefined {
  const phase = execution.phases.find((p) => p.session_id === sessionId)
  if (!phase) return undefined
  return {
    answer: {
      pins: phase.pinned_at_start ?? null,
      status: phase.start_pins_status ?? 'unavailable',
      skillUse: phase.skill_use,
    },
    live: !isTerminalExecutionStatus(execution.status) && !isTerminalExecutionStatus(phase.status),
  }
}

/**
 * Ask until the server gives an answer (`recorded` or `not_recorded`), the
 * signal aborts, or MAX_ATTEMPTS is reached; then, while the phase is still
 * running, keep re-reading every liveMs so its skill use stays current.
 * Returns the pending-timer cleanup.
 */
function askUntilAnswered(
  ask: () => Promise<Reading | undefined>,
  onAnswer: (answer: PhaseStartPinsAnswer) => void,
  signal: AbortSignal,
  retryMs: number,
  liveMs: number,
): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined
  let attempts = 0
  const attempt = async () => {
    // A failed request is not an answer either: stay unknown and retry.
    const reading = await ask().catch(() => undefined)
    if (signal.aborted) return
    if (reading) onAnswer(reading.answer)
    const answered = reading !== undefined && reading.answer.status !== 'unavailable'
    if (answered) {
      // Pins are fixed, skill use is not: the bound is the phase ending,
      // which a live phase reaches, not an attempt count.
      if (reading.live) timer = setTimeout(() => void attempt(), liveMs)
      return
    }
    attempts += 1
    if (attempts < MAX_ATTEMPTS) timer = setTimeout(() => void attempt(), retryMs)
  }
  void attempt()
  return () => clearTimeout(timer)
}

/**
 * What the phase that ran the given session had at start (#1454), and which of
 * its skills it has invoked so far (#1269), for a session page.
 *
 * The pins are fixed when the execution starts, but skill use grows while the
 * phase runs: once the server has answered `recorded` or `not_recorded`, the
 * hook re-reads every LIVE_REFRESH_MS until the phase or execution reaches a
 * terminal status, and then asks nothing more. Before that answer it
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
  liveMs: number = LIVE_REFRESH_MS,
): PhaseStartPinsAnswer | undefined {
  // Tagged with the session it answers for, so a stale answer reads as unknown
  // after navigating to another session instead of describing the wrong phase.
  const [answer, setAnswer] = useState<{ sessionId: string } & PhaseStartPinsAnswer>()

  useEffect(() => {
    if (!executionId || !sessionId) return
    const controller = new AbortController()
    const stop = askUntilAnswered(
      () => getExecution(executionId, controller.signal).then((e) => readingFor(e, sessionId)),
      (found) => setAnswer({ sessionId, ...found }),
      controller.signal,
      retryMs,
      liveMs,
    )
    return () => {
      controller.abort()
      stop()
    }
  }, [executionId, sessionId, retryMs, liveMs])

  return answer && answer.sessionId === sessionId
    ? { pins: answer.pins, status: answer.status, skillUse: answer.skillUse }
    : undefined
}
