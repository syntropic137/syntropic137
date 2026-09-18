/**
 * The React half of #1095: what a component's lifecycle does to the loop.
 *
 * The loop's own behaviour is pinned in `serialRefreshLoop.test.ts` and is not
 * repeated here. What only shows up through React is the order the effects run
 * in - a remount tears the loop down and brings it back, and the options have
 * to be reported to a loop that is alive again, or the surface comes back
 * without a timer.
 */

import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'

import { RUNNING_POLL_INTERVAL_MS, useSerialRefresh } from '../useSerialRefresh'

describe('useSerialRefresh', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('polls after a StrictMode remount, which tears the loop down and back up', async () => {
    const fetch = vi.fn(() => Promise.resolve())

    const { unmount } = renderHook(
      () => useSerialRefresh({ fetch, pollIntervalMs: RUNNING_POLL_INTERVAL_MS }),
      { wrapper: StrictMode },
    )

    // Nobody has called `refetch`: this poll can only come from the timer the
    // mount set, which is the thing a remount can lose.
    await vi.advanceTimersByTimeAsync(RUNNING_POLL_INTERVAL_MS)
    expect(fetch).toHaveBeenCalledTimes(1)

    unmount()
    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('stops polling when the surface says it no longer wants to be polled', async () => {
    const fetch = vi.fn(() => Promise.resolve())

    const { rerender, unmount } = renderHook(
      ({ pollIntervalMs }: { pollIntervalMs: number | null }) =>
        useSerialRefresh({ fetch, pollIntervalMs }),
      { initialProps: { pollIntervalMs: RUNNING_POLL_INTERVAL_MS as number | null } },
    )

    await vi.advanceTimersByTimeAsync(RUNNING_POLL_INTERVAL_MS)
    expect(fetch).toHaveBeenCalledTimes(1)

    rerender({ pollIntervalMs: null })
    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetch).toHaveBeenCalledTimes(1)

    unmount()
  })
})
