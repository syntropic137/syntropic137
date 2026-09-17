/**
 * The loop's own tests. The point of splitting it out of the hook is that the
 * decisions - run now or fold, what a settling answer means, when the next
 * poll is due - are answerable without React and without a live request, so
 * that is how they are tested here.
 *
 * The behaviour these pin is #1095's acceptance: never more than one request
 * in flight per resource, a poll that arrives while its predecessor is
 * outstanding is folded rather than queued, and the gap between polls comes
 * from the latency actually observed rather than from a constant.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createSerialRefreshLoop,
  decideOnSettle,
  decideRefetch,
  nextPollDelayMs,
} from '../serialRefreshLoop'

const POLL_FLOOR_MS = 3000

function setVisibility(state: 'visible' | 'hidden'): void {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true })
}

/** A fetcher that answers only when the test says so. */
function controllableFetch(): {
  fetch: () => Promise<void>
  settleOldest: () => void
  calls: () => number
} {
  const pending: Array<() => void> = []
  const fetch = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        pending.push(resolve)
      }),
  )
  return {
    fetch,
    settleOldest: () => pending.shift()?.(),
    calls: () => fetch.mock.calls.length,
  }
}

/** Let queued microtasks run without moving the clock. */
async function flush(): Promise<void> {
  await vi.advanceTimersByTimeAsync(0)
}

describe('decideRefetch', () => {
  it('starts when nothing is outstanding', () => {
    expect(decideRefetch({ disposed: false, inFlight: false })).toBe('start')
  })

  it('folds into the outstanding request rather than opening a second one', () => {
    expect(decideRefetch({ disposed: false, inFlight: true })).toBe('fold')
  })

  it('ignores an ask from a surface that has gone away, outstanding or not', () => {
    expect(decideRefetch({ disposed: true, inFlight: false })).toBe('ignore')
    expect(decideRefetch({ disposed: true, inFlight: true })).toBe('ignore')
  })
})

describe('decideOnSettle', () => {
  const live = { generation: 7, disposed: false, trailing: false }

  it('abandons an answer to a request that has been superseded', () => {
    expect(decideOnSettle(live, 6)).toBe('abandon')
  })

  it('abandons it even when the loop would otherwise have work to do', () => {
    // The stale answer must not consume the trailing ask: that ask is waiting
    // on the request that replaced it.
    expect(decideOnSettle({ ...live, trailing: true }, 6)).toBe('abandon')
  })

  it('stops when the surface went away while the request was on the wire', () => {
    expect(decideOnSettle({ ...live, disposed: true }, 7)).toBe('stop')
  })

  it('reruns once for however many asks arrived while it was outstanding', () => {
    expect(decideOnSettle({ ...live, trailing: true }, 7)).toBe('rerun')
  })

  it('schedules the next poll when nothing is pending', () => {
    expect(decideOnSettle(live, 7)).toBe('schedule')
  })
})

describe('nextPollDelayMs', () => {
  afterEach(() => {
    setVisibility('visible')
  })

  it('waits out the latency when the endpoint is slower than the floor', () => {
    // 12s is four times the floor and is not a constant anywhere in the
    // production code: only a gap derived from THIS latency produces it.
    expect(nextPollDelayMs({ pollIntervalMs: 3000, latencyMs: 12_000, disposed: false })).toBe(
      12_000,
    )
  })

  it('holds the floor when the endpoint is faster than it', () => {
    expect(nextPollDelayMs({ pollIntervalMs: 3000, latencyMs: 40, disposed: false })).toBe(3000)
  })

  it('has no next poll for a surface that did not ask to be polled', () => {
    expect(nextPollDelayMs({ pollIntervalMs: null, latencyMs: 12_000, disposed: false })).toBeNull()
  })

  it('has no next poll for a surface that has gone away', () => {
    expect(nextPollDelayMs({ pollIntervalMs: 3000, latencyMs: 40, disposed: true })).toBeNull()
  })

  it('has no next poll while nobody is looking at the tab', () => {
    setVisibility('hidden')
    expect(nextPollDelayMs({ pollIntervalMs: 3000, latencyMs: 40, disposed: false })).toBeNull()
  })
})

describe('createSerialRefreshLoop', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setVisibility('visible')
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('opens no second request while one is outstanding, however far past the floor', async () => {
    const endpoint = controllableFetch()
    const loop = createSerialRefreshLoop({ fetch: endpoint.fetch, pollIntervalMs: POLL_FLOOR_MS })
    loop.activate()
    loop.reconfigure({ fetch: endpoint.fetch, pollIntervalMs: POLL_FLOOR_MS })
    expect(vi.getTimerCount()).toBe(1)

    loop.refetch()
    await flush()
    expect(endpoint.calls()).toBe(1)

    // Structural, not incidental: while a request is outstanding there is no
    // timer at all. A poll CANNOT overlap one because there is no tick to skip.
    expect(vi.getTimerCount()).toBe(0)

    // Six floor intervals with that request still on the wire, and the surface
    // asking again on each of them - SSE frames, a filter change, a poll that
    // cannot see the request. A loop that fires on every one of them is the
    // pile-up in pg_stat_activity.
    for (let i = 0; i < 6; i++) {
      await vi.advanceTimersByTimeAsync(POLL_FLOOR_MS)
      loop.refetch()
    }
    await flush()
    expect(endpoint.calls()).toBe(1)

    loop.deactivate()
  })

  it('folds a burst of twenty asks into the one run that follows, not twenty', async () => {
    const endpoint = controllableFetch()
    const loop = createSerialRefreshLoop({ fetch: endpoint.fetch, pollIntervalMs: POLL_FLOOR_MS })
    loop.activate()

    loop.refetch()
    await flush()
    expect(endpoint.calls()).toBe(1)

    for (let i = 0; i < 20; i++) loop.refetch()
    await flush()
    expect(endpoint.calls()).toBe(1)

    endpoint.settleOldest()
    await flush()
    expect(endpoint.calls()).toBe(2)

    // And the twenty are spent: the second run is not followed by nineteen
    // more queued behind it.
    endpoint.settleOldest()
    await flush()
    expect(endpoint.calls()).toBe(2)

    loop.deactivate()
  })

  it('spaces the next poll by how long the answer took, not by the floor', async () => {
    const LATENCY_MS = 12_000
    const endpoint = controllableFetch()
    const loop = createSerialRefreshLoop({ fetch: endpoint.fetch, pollIntervalMs: POLL_FLOOR_MS })
    loop.activate()

    loop.refetch()
    await flush()
    await vi.advanceTimersByTimeAsync(LATENCY_MS)
    endpoint.settleOldest()
    await flush()

    // Ten more seconds: three floor intervals, on which a constant-paced poll
    // would have fired three times.
    await vi.advanceTimersByTimeAsync(10_000)
    expect(endpoint.calls()).toBe(1)

    // The gap is the observed 12s, so the poll lands at 12s and not before.
    await vi.advanceTimersByTimeAsync(2000)
    expect(endpoint.calls()).toBe(2)

    loop.deactivate()
  })

  it('starts the new request at once when what is being fetched changes', async () => {
    const stale = controllableFetch()
    const fresh = controllableFetch()
    const loop = createSerialRefreshLoop({ fetch: stale.fetch, pollIntervalMs: POLL_FLOOR_MS })
    loop.activate()

    loop.refetch()
    await flush()
    expect(stale.calls()).toBe(1)

    // A new id: the outstanding answer is about something nobody is looking at
    // any more, so asking again must not wait behind it.
    loop.reconfigure({ fetch: fresh.fetch, pollIntervalMs: POLL_FLOOR_MS })
    loop.refetch()
    await flush()
    expect(fresh.calls()).toBe(1)

    // The abandoned answer arrives late and decides nothing - in particular it
    // does not report the loop idle, which would let the next ask open a second
    // request alongside the one still on the wire.
    stale.settleOldest()
    await flush()
    loop.refetch()
    await flush()
    expect(fresh.calls()).toBe(1)

    loop.deactivate()
  })

  it('does not poll a hidden tab, and catches up once when it comes back', async () => {
    const endpoint = controllableFetch()
    const loop = createSerialRefreshLoop({ fetch: endpoint.fetch, pollIntervalMs: POLL_FLOOR_MS })
    loop.activate()

    loop.refetch()
    await flush()
    endpoint.settleOldest()
    await flush()
    expect(endpoint.calls()).toBe(1)

    // Hidden after the poll was scheduled, and with nothing dispatched: a tab
    // can go away without the loop being told, and a hidden tab must not poll.
    setVisibility('hidden')
    await vi.advanceTimersByTimeAsync(18_000)
    expect(endpoint.calls()).toBe(1)

    setVisibility('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    await flush()
    expect(endpoint.calls()).toBe(2)

    loop.deactivate()
    setVisibility('visible')
  })

  it('stops polling and lets go of the tab once deactivated', async () => {
    const endpoint = controllableFetch()
    const loop = createSerialRefreshLoop({ fetch: endpoint.fetch, pollIntervalMs: POLL_FLOOR_MS })
    loop.activate()

    loop.refetch()
    await flush()
    endpoint.settleOldest()
    await flush()
    expect(endpoint.calls()).toBe(1)

    loop.deactivate()
    await vi.advanceTimersByTimeAsync(18_000)
    expect(endpoint.calls()).toBe(1)

    // Nor by either of the two routes that bypass the timer.
    loop.refetch()
    document.dispatchEvent(new Event('visibilitychange'))
    await flush()
    expect(endpoint.calls()).toBe(1)
  })

  it('resumes polling when the same loop is activated again', async () => {
    // What a StrictMode remount does to the loop: deactivate, activate, and
    // the options reported again on the same state.
    const endpoint = controllableFetch()
    const loop = createSerialRefreshLoop({ fetch: endpoint.fetch, pollIntervalMs: POLL_FLOOR_MS })
    loop.activate()
    loop.deactivate()
    loop.activate()
    loop.reconfigure({ fetch: endpoint.fetch, pollIntervalMs: POLL_FLOOR_MS })

    await vi.advanceTimersByTimeAsync(POLL_FLOOR_MS)
    expect(endpoint.calls()).toBe(1)

    loop.deactivate()
  })
})
