import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { usePolling } from '../usePolling'

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('calls callback at the specified interval when enabled', () => {
    const callback = vi.fn()
    renderHook(() => usePolling(callback, 1000, true))

    expect(callback).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1000)
    expect(callback).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(2000)
    expect(callback).toHaveBeenCalledTimes(3)
  })

  it('does not call callback when disabled', () => {
    const callback = vi.fn()
    renderHook(() => usePolling(callback, 1000, false))

    vi.advanceTimersByTime(5000)
    expect(callback).not.toHaveBeenCalled()
  })

  it('cleans up on unmount', () => {
    const callback = vi.fn()
    const { unmount } = renderHook(() => usePolling(callback, 1000, true))

    vi.advanceTimersByTime(1000)
    expect(callback).toHaveBeenCalledTimes(1)

    unmount()
    vi.advanceTimersByTime(5000)
    expect(callback).toHaveBeenCalledTimes(1)
  })

  it('stops polling when enabled changes to false', () => {
    const callback = vi.fn()
    const { rerender } = renderHook(
      ({ enabled }) => usePolling(callback, 1000, enabled),
      { initialProps: { enabled: true } },
    )

    vi.advanceTimersByTime(2000)
    expect(callback).toHaveBeenCalledTimes(2)

    rerender({ enabled: false })
    vi.advanceTimersByTime(5000)
    expect(callback).toHaveBeenCalledTimes(2)
  })
})
