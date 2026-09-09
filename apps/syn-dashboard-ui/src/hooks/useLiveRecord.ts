/**
 * Keeps ONE record current from its execution's SSE stream.
 *
 * `useLiveRefresh` does this for a list off the global activity feed. A detail
 * view needs the per-execution feed instead, because activity only carries
 * lifecycle transitions and a detail view also moves on phases, artifacts and
 * every operation the agent records.
 *
 * Three triggers, same reasoning as `useLiveRefresh` and one more:
 *
 *   - SSE frames whose event type means THIS record changed. Bursty, so the
 *     refetch is throttled.
 *   - Every (re)connect. `/sse/executions/{id}` has no `Last-Event-ID` and no
 *     replay, so anything published while the socket was down is simply gone.
 *     A reconnect can only be assumed to have missed frames; one refetch on
 *     open is what makes "subscribe, don't poll" safe rather than optimistic.
 *   - A poll while the stream is NOT delivering — no execution to subscribe
 *     to, or the connection is down — so a dead stream degrades to slow
 *     rather than to wrong.
 *
 * The interval is deliberately slower than the 3s the detail views used to
 * poll at unconditionally: it is now a fallback rather than the primary
 * channel, and it must stay above the p99 of the endpoint it calls or it
 * queues requests behind each other (#1095).
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useEffect, useRef } from 'react'
import type { SSEEventFrame } from '../types'
import { useExecutionStream } from './useExecutionStream'
import { useRefetchWhileRunning } from './useRefetchWhileRunning'
import { useThrottledRefetch } from './useThrottledRefetch'

/**
 * Ceiling on event-driven refetches.
 *
 * This is the number that decides whether subscribing is actually cheaper than
 * polling, and it is easy to get backwards. `useLiveRefresh` throttles list
 * refetches at 500ms because activity frames are rare — a run starts, a run
 * ends. A detail view subscribes to `OperationRecorded`, which fires on every
 * message and every tool call, so an agent working quickly can produce frames
 * several times a second. At 500ms that would be up to 120 requests a minute
 * against an endpoint the page used to ask 20 times a minute: the change would
 * make the load worse, on exactly the endpoint #1095 is about.
 *
 * 3000ms is the cadence the detail views used to poll at, so freshness is
 * unchanged and the request rate can never exceed what it replaced. What
 * changes is that requests now happen only when something happened: an agent
 * thinking for a minute costs nothing, and a finished run costs nothing at all.
 */
const REFETCH_THROTTLE_MS = 3000

/**
 * Fallback poll cadence, used only while the stream is not delivering.
 *
 * 10s clears the measured p99 of both endpoints it backs — `/executions/{id}`
 * and `/sessions/{id}` — with room to spare. The old 3s did not reliably clear
 * `/sessions`, and an interval shorter than the response it waits for is a
 * queue by construction (#1095).
 */
const DISCONNECTED_POLL_MS = 10_000

export interface UseLiveRecordOptions<TRecord> {
  /** The execution channel to subscribe to. Undefined → poll only. */
  executionId: string | undefined
  /** The record on screen, or null before the first fetch lands. */
  record: TRecord | null
  /** False while the record is still moving, which keeps the fallback poll alive. */
  isTerminal: (record: TRecord) => boolean
  refetch: () => void
  /** Event types that mean "this record changed". */
  liveEvents: ReadonlySet<string>
  /**
   * Narrows an execution's frames to the ones this record cares about.
   *
   * An execution channel carries every session in the run, so a session detail
   * view must ignore its siblings. Defaults to "all of them", which is right
   * for a view of the execution itself.
   */
  concerns?: (frame: SSEEventFrame) => boolean
}

export interface LiveRecordState {
  connected: boolean
}

export function useLiveRecord<TRecord>({
  executionId,
  record,
  isTerminal,
  refetch,
  liveEvents,
  concerns,
}: UseLiveRecordOptions<TRecord>): LiveRecordState {
  const scheduleRefetch = useThrottledRefetch(refetch, REFETCH_THROTTLE_MS)

  // Held in refs so a caller passing an inline predicate never tears down and
  // reopens the EventSource on every render.
  const concernsRef = useRef(concerns)
  const liveEventsRef = useRef(liveEvents)
  useEffect(() => {
    concernsRef.current = concerns
    liveEventsRef.current = liveEvents
  }, [concerns, liveEvents])

  const handleFrame = useCallback(
    (frame: SSEEventFrame) => {
      if (frame.type !== 'event') return
      if (!liveEventsRef.current.has(frame.event_type)) return
      if (concernsRef.current && !concernsRef.current(frame)) return
      scheduleRefetch()
    },
    [scheduleRefetch],
  )

  const { isConnected } = useExecutionStream(executionId, { onEvent: handleFrame })

  // Close the reconnect gap: the stream has no replay, so an open socket is
  // only trustworthy from the moment it opened.
  useEffect(() => {
    if (isConnected) refetch()
  }, [isConnected, refetch])

  // While the stream is up it carries every change this record has, so nothing
  // needs polling. An empty list is how `useRefetchWhileRunning` is told that.
  const pollTargets = isConnected || record === null ? [] : [record]
  useRefetchWhileRunning({
    items: pollTargets,
    isTerminal,
    refetch,
    intervalMs: DISCONNECTED_POLL_MS,
  })

  return { connected: isConnected }
}

export default useLiveRecord
