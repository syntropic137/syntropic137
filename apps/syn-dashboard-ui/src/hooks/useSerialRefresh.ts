/**
 * One resource, one request at a time, at a cadence the server can serve.
 *
 * A dashboard surface has several reasons to ask for the same thing again -
 * the page mounted, a filter changed, SSE said it changed, and a poll keeps
 * Lane 2 numbers ticking. Each used to own a timer and fire into the void:
 * `refetch()` returned `void`, so nothing could tell whether the previous
 * answer had arrived. When an endpoint got slower than the interval, every
 * tick started another query and they stacked - three concurrent copies of
 * the same 18-second query in `pg_stat_activity`, on a box already slow
 * enough to be the reason they overlapped (#1095).
 *
 * So the triggers no longer hold timers. They call `refetch()`, and this owns
 * what happens next:
 *
 *   - A request that arrives while one is outstanding does not start a second
 *     one. It runs once, after, and several arriving together still run once -
 *     bounded at one in flight and one behind it, never a queue.
 *   - A poll is scheduled only from the completion of the previous request, so
 *     a poll CANNOT overlap one. There is no guard to get wrong, and no tick
 *     to skip, because a tick while busy never happens.
 *   - The gap is `max(pollIntervalMs, how long the last answer took)`. The
 *     floor is what the surface wants; the latency is what the server can
 *     actually give. An endpoint that degrades to 18s is polled every 18s
 *     instead of every 3s, and speeds back up on its own when the endpoint
 *     does. Nothing here is a fixed interval - a fixed interval is what
 *     created the pile-up.
 *   - A hidden tab polls not at all, and refreshes once when it comes back.
 *
 * Callers see one function. They cannot observe or influence the sequencing,
 * so they cannot reintroduce the overlap.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useEffect, useRef } from 'react'

/**
 * Floor for re-reading something that is still running. SSE reports lifecycle
 * transitions; Lane 2 (tokens, cost, duration) moves continuously in between,
 * and this is how often that movement is worth fetching.
 */
export const RUNNING_POLL_INTERVAL_MS = 3000

/**
 * Floor for standing in for a stream that is not connected, so a dropped
 * connection degrades to slow rather than to wrong.
 */
export const DISCONNECTED_POLL_INTERVAL_MS = 5000

export interface UseSerialRefreshOptions {
  /**
   * Fetch the resource and apply the result. Awaited, so the loop knows when
   * the answer landed; a rejection is the caller's to report, and only ends
   * this attempt.
   */
  fetch: () => Promise<void>
  /**
   * Shortest gap between polls, or `null` to not poll at all. The real gap is
   * this or the last observed latency, whichever is longer. Changing it
   * re-times the next poll; it never starts a second one.
   */
  pollIntervalMs: number | null
}

export interface SerialRefresh {
  /**
   * Ask for fresh data. Runs now if nothing is outstanding, otherwise once the
   * outstanding request finishes. Stable for the lifetime of the component.
   */
  refetch: () => void
}

interface LoopState {
  fetch: () => Promise<void>
  pollIntervalMs: number | null
  /** A request has been issued and has not settled. */
  inFlight: boolean
  /** Someone asked while `inFlight`; run exactly once more on settle. */
  trailing: boolean
  /** How long the last completed request took. */
  latencyMs: number
  /**
   * Which request the loop is currently waiting on. Bumping it abandons the
   * outstanding one: its answer may still arrive, but it no longer decides
   * what happens next.
   */
  generation: number
  timer: ReturnType<typeof setTimeout> | null
  /** The component has unmounted; stop scheduling. */
  disposed: boolean
}

function isTabHidden(): boolean {
  return typeof document !== 'undefined' && document.visibilityState === 'hidden'
}

export function useSerialRefresh({ fetch, pollIntervalMs }: UseSerialRefreshOptions): SerialRefresh {
  const stateRef = useRef<LoopState>({
    fetch,
    pollIntervalMs,
    inFlight: false,
    trailing: false,
    latencyMs: 0,
    generation: 0,
    timer: null,
    disposed: false,
  })

  // `run` schedules the next poll and the poll calls `run`. The ref breaks that
  // cycle so neither has to be defined first; it is assigned below, before any
  // timer this hook sets can fire.
  const runRef = useRef<() => void>(() => {})

  // `fetch` changes identity whenever what it would fetch changes - a new query,
  // a new id. That is the one case where asking again must NOT wait its turn:
  // what is outstanding is an answer about something the caller has stopped
  // looking at, and its result will be discarded either way. So it is abandoned
  // rather than waited for, and the caller's refetch starts the new request
  // immediately. Still one request in flight - a different one.
  //
  // Asking again for the SAME thing is the opposite case and does wait, because
  // there the outstanding request is already fetching exactly what was asked
  // for. That difference is what stops a page change costing two round trips
  // back to back on a slow endpoint.
  useEffect(() => {
    const state = stateRef.current
    if (state.fetch === fetch) return
    state.fetch = fetch
    if (state.inFlight) {
      state.generation += 1
      state.inFlight = false
      state.trailing = false
    }
  }, [fetch])

  const clearTimer = useCallback(() => {
    const state = stateRef.current
    if (state.timer !== null) {
      clearTimeout(state.timer)
      state.timer = null
    }
  }, [])

  const scheduleNextPoll = useCallback(() => {
    const state = stateRef.current
    clearTimer()
    if (state.disposed || state.pollIntervalMs === null || isTabHidden()) return
    const delay = Math.max(state.pollIntervalMs, state.latencyMs)
    state.timer = setTimeout(() => {
      stateRef.current.timer = null
      // Re-checked here, not just above: a tab can be hidden after the timer is
      // set, and a hidden tab must not poll even if nothing told us it went
      // away. `visibilitychange` is what resumes it.
      if (isTabHidden()) return
      runRef.current()
    }, delay)
  }, [clearTimer])

  const run = useCallback(() => {
    const state = stateRef.current
    if (state.disposed) return
    if (state.inFlight) {
      state.trailing = true
      return
    }

    state.inFlight = true
    clearTimer()
    const generation = ++state.generation
    const startedAt = Date.now()

    // `Promise.resolve().then(...)` so a fetcher that throws synchronously is
    // handled the same as one that rejects, rather than escaping and leaving
    // `inFlight` stuck true - which would wedge the loop permanently.
    void Promise.resolve()
      .then(() => state.fetch())
      .catch(() => {
        // The fetcher reports its own failures. A failed attempt still counts
        // as an attempt: it settled, so the next poll is scheduled normally.
      })
      .finally(() => {
        // Abandoned while in flight: something newer is already running, and
        // this answer must not touch the loop's bookkeeping or its timing.
        if (generation !== state.generation) return
        state.latencyMs = Date.now() - startedAt
        state.inFlight = false
        if (state.disposed) return
        if (state.trailing) {
          state.trailing = false
          runRef.current()
          return
        }
        scheduleNextPoll()
      })
  }, [clearTimer, scheduleNextPoll])

  useEffect(() => {
    runRef.current = run
  }, [run])

  useEffect(() => {
    const state = stateRef.current
    // Reset rather than assume false: StrictMode remounts reuse these refs.
    state.disposed = false
    return () => {
      state.disposed = true
      clearTimer()
    }
  }, [clearTimer])

  useEffect(() => {
    const state = stateRef.current
    state.pollIntervalMs = pollIntervalMs
    if (pollIntervalMs === null) {
      clearTimer()
      return
    }
    // A request in flight schedules the next poll when it settles; scheduling
    // here too would put a second timer on the same loop.
    if (!state.inFlight) scheduleNextPoll()
  }, [pollIntervalMs, clearTimer, scheduleNextPoll])

  useEffect(() => {
    if (typeof document === 'undefined') return
    const onVisibilityChange = () => {
      if (isTabHidden()) {
        clearTimer()
        return
      }
      // Coming back to a surface that polls: catch up immediately rather than
      // showing whatever was on screen when the tab was hidden.
      if (stateRef.current.pollIntervalMs !== null) runRef.current()
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [clearTimer])

  return { refetch: run }
}
