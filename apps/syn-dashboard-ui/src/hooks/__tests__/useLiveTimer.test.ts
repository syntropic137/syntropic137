import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useLiveTimer } from '../useLiveTimer'

describe('useLiveTimer', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns initial timestamp', () => {
    const { result } = renderHook(() => useLiveTimer(false))
    expect(typeof result.current).toBe('number')
    expect(result.current).toBeGreaterThan(0)
  })

  it('updates timestamp at interval when enabled', () => {
    const { result } = renderHook(() => useLiveTimer(true, 1000))
    const initial = result.current

    act(() => {
      vi.advanceTimersByTime(1000)
    })

    expect(result.current).toBeGreaterThanOrEqual(initial)
  })

  it('does not update when disabled', () => {
    const { result } = renderHook(() => useLiveTimer(false, 1000))
    const initial = result.current

    act(() => {
      vi.advanceTimersByTime(5000)
    })

    expect(result.current).toBe(initial)
  })

  it('cleans up on unmount', () => {
    const spy = vi.spyOn(globalThis, 'clearInterval')
    const { unmount } = renderHook(() => useLiveTimer(true, 1000))

    unmount()
    expect(spy).toHaveBeenCalled()
    spy.mockRestore()
  })
})
