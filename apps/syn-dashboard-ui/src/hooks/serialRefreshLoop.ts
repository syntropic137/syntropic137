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
 * So the triggers no longer hold timers. They ask this loop, and it owns what
 * happens next:
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
 * Four verbs, and none of them expose the sequencing: a caller can say what it
 * wants fetched and when it is alive, and cannot observe or influence whether a
 * request is outstanding. So it cannot reintroduce the overlap.
 *
 * The decisions the loop makes - run now or fold into the outstanding request,
 * what a settling answer means, when the next poll is due - are the exported
 * pure functions below. They are the part worth testing, and they need neither
 * React nor a live request to test.
 *
 * `useSerialRefresh` is the React binding for this. There is no other caller;
 * the split is so that mount/unmount is the only thing the React layer knows.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

export interface SerialRefreshOptions {
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

export interface SerialRefreshLoop {
  /**
   * Ask for fresh data. Runs now if nothing is outstanding, otherwise once the
   * outstanding request finishes. Stable for the lifetime of the loop.
   */
  refetch: () => void
  /**
   * The caller now wants something else fetched, or wants it at a different
   * cadence. Which of those has consequences for the outstanding request is
   * the loop's business, not the caller's.
   */
  reconfigure: (options: SerialRefreshOptions) => void
  /** The surface is on screen: poll, and watch for the tab being hidden. */
  activate: () => void
  /** The surface is gone: stop scheduling and let go of the tab. */
  deactivate: () => void
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
  /** The surface has gone away; stop scheduling. */
  disposed: boolean
  /** Non-null exactly while subscribed to the tab. */
  visibilityListener: (() => void) | null
}

/** What the loop already knows when it works out when to poll next. */
export interface PollTiming {
  readonly pollIntervalMs: number | null
  readonly latencyMs: number
  readonly disposed: boolean
}

/** What a request for fresh data does, given what is already outstanding. */
export type RefetchDecision =
  /** Nothing outstanding: go now. */
  | 'start'
  /**
   * One outstanding: fold into the single run that follows it. A twentieth
   * asker gets the same one run the first asker got - bounded, not queued.
   */
  | 'fold'
  /** The surface is gone; nobody is waiting for this answer. */
  | 'ignore'

/** What a settling request means for the loop that is still running. */
export type SettleDecision =
  /**
   * Something newer replaced this request while it was on the wire. Its answer
   * must touch neither the bookkeeping nor the timing: the newer request owns
   * both, and this latency is for a resource nobody is looking at.
   */
  | 'abandon'
  /** The surface went away while this was on the wire. */
  | 'stop'
  /** Someone asked while this was outstanding; that is the one run they get. */
  | 'rerun'
  /** Nothing pending: wait out the gap and poll. */
  | 'schedule'

function isTabHidden(): boolean {
  return typeof document !== 'undefined' && document.visibilityState === 'hidden'
}

/**
 * How long until the next poll, or `null` if there is not going to be one.
 *
 * The three reasons not to poll are one decision, not three checks spread over
 * the loop: a surface that has gone away, a surface that never wanted polling,
 * and a tab nobody is looking at.
 */
export function nextPollDelayMs(timing: PollTiming): number | null {
  if (timing.disposed || timing.pollIntervalMs === null || isTabHidden()) return null
  return Math.max(timing.pollIntervalMs, timing.latencyMs)
}

export function decideRefetch(state: {
  readonly disposed: boolean
  readonly inFlight: boolean
}): RefetchDecision {
  if (state.disposed) return 'ignore'
  if (state.inFlight) return 'fold'
  return 'start'
}

export function decideOnSettle(
  state: { readonly generation: number; readonly disposed: boolean; readonly trailing: boolean },
  generation: number,
): SettleDecision {
  if (generation !== state.generation) return 'abandon'
  if (state.disposed) return 'stop'
  if (state.trailing) return 'rerun'
  return 'schedule'
}

function clearTimer(state: LoopState): void {
  if (state.timer === null) return
  clearTimeout(state.timer)
  state.timer = null
}

function scheduleNextPoll(state: LoopState): void {
  clearTimer(state)
  const delay = nextPollDelayMs(state)
  if (delay === null) return
  state.timer = setTimeout(() => {
    state.timer = null
    // Re-checked here, not just above: a tab can be hidden after the timer is
    // set, and a hidden tab must not poll even if nothing told us it went
    // away. `visibilitychange` is what resumes it.
    if (isTabHidden()) return
    refetch(state)
  }, delay)
}

function refetch(state: LoopState): void {
  const decision = decideRefetch(state)
  if (decision === 'ignore') return
  if (decision === 'fold') {
    state.trailing = true
    return
  }

  state.inFlight = true
  clearTimer(state)
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
    .finally(() => settle(state, generation, startedAt))
}

function settle(state: LoopState, generation: number, startedAt: number): void {
  const decision = decideOnSettle(state, generation)
  if (decision === 'abandon') return
  state.latencyMs = Date.now() - startedAt
  state.inFlight = false
  if (decision === 'stop') return
  if (decision === 'rerun') {
    state.trailing = false
    refetch(state)
    return
  }
  scheduleNextPoll(state)
}

/**
 * `fetch` changes identity whenever what it would fetch changes - a new query,
 * a new id. That is the one case where asking again must NOT wait its turn:
 * what is outstanding is an answer about something the caller has stopped
 * looking at, and its result will be discarded either way. So it is abandoned
 * rather than waited for, and the caller's refetch starts the new request
 * immediately. Still one request in flight - a different one.
 *
 * Asking again for the SAME thing is the opposite case and does wait, because
 * there the outstanding request is already fetching exactly what was asked
 * for. That difference is what stops a page change costing two round trips
 * back to back on a slow endpoint.
 */
function retarget(state: LoopState, fetch: () => Promise<void>): void {
  if (state.fetch === fetch) return
  state.fetch = fetch
  if (!state.inFlight) return
  state.generation += 1
  state.inFlight = false
  state.trailing = false
}

function reconfigure(state: LoopState, options: SerialRefreshOptions): void {
  retarget(state, options.fetch)
  state.pollIntervalMs = options.pollIntervalMs
  // A surface that has just asked to stop polling needs no branch of its own:
  // rescheduling clears the pending timer first and then declines to set one.
  //
  // A request in flight is the case that does: it schedules the next poll when
  // it settles, and scheduling here too would put a second timer on the loop.
  if (!state.inFlight) scheduleNextPoll(state)
}

function onTabVisibilityChanged(state: LoopState): void {
  if (isTabHidden()) {
    clearTimer(state)
    return
  }
  // Coming back to a surface that polls: catch up immediately rather than
  // showing whatever was on screen when the tab was hidden.
  if (state.pollIntervalMs !== null) refetch(state)
}

function activate(state: LoopState): void {
  // Reset rather than assume false: a loop is reactivated when React remounts
  // the component under StrictMode, on the same state.
  state.disposed = false
  if (typeof document === 'undefined' || state.visibilityListener !== null) return
  const listener = () => onTabVisibilityChanged(state)
  state.visibilityListener = listener
  document.addEventListener('visibilitychange', listener)
}

function deactivate(state: LoopState): void {
  state.disposed = true
  clearTimer(state)
  if (state.visibilityListener === null) return
  document.removeEventListener('visibilitychange', state.visibilityListener)
  state.visibilityListener = null
}

export function createSerialRefreshLoop(options: SerialRefreshOptions): SerialRefreshLoop {
  const state: LoopState = {
    fetch: options.fetch,
    pollIntervalMs: options.pollIntervalMs,
    inFlight: false,
    trailing: false,
    latencyMs: 0,
    generation: 0,
    timer: null,
    disposed: false,
    visibilityListener: null,
  }

  return {
    refetch: () => refetch(state),
    reconfigure: (next) => reconfigure(state, next),
    activate: () => activate(state),
    deactivate: () => deactivate(state),
  }
}
