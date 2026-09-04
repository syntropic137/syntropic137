import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useSessionData } from '../useSessionData'

vi.mock('../../api/sessions', () => ({
  getSession: vi.fn(),
}))

import { getSession } from '../../api/sessions'

const mockGetSession = vi.mocked(getSession)

const makeSession = (overrides = {}) => ({
  session_id: 'sess-1',
  status: 'completed',
  started_at: '2026-03-23T00:00:00Z',
  completed_at: '2026-03-23T00:05:00Z',
  total_tokens: 1000,
  operations: [],
  subagents: [],
  ...overrides,
})

describe('useSessionData', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches session on mount', async () => {
    const session = makeSession()
    mockGetSession.mockResolvedValue(session as never)

    const { result } = renderHook(() => useSessionData('sess-1'))

    expect(result.current.loading).toBe(true)

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.session).toEqual(session)
    expect(result.current.error).toBeNull()
    expect(mockGetSession).toHaveBeenCalledWith('sess-1', expect.any(AbortSignal))
  })

  it('handles fetch error', async () => {
    mockGetSession.mockRejectedValue(new Error('Network error'))

    const { result } = renderHook(() => useSessionData('sess-1'))

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.error).toBe('Network error')
    expect(result.current.session).toBeNull()
  })

  it('does not fetch when sessionId is undefined', () => {
    renderHook(() => useSessionData(undefined))
    expect(mockGetSession).not.toHaveBeenCalled()
  })

  it('initializes showConversationLog as false', async () => {
    mockGetSession.mockResolvedValue(makeSession() as never)
    const { result } = renderHook(() => useSessionData('sess-1'))

    expect(result.current.showConversationLog).toBe(false)
  })

  describe('live polling (#1048)', () => {
    beforeEach(() => {
      vi.useFakeTimers()
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        configurable: true,
      })
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('pauses while hidden and resumes with an immediate refetch when the tab becomes visible again', async () => {
      mockGetSession.mockResolvedValue(makeSession({ status: 'running' }) as never)

      const { result } = renderHook(() => useSessionData('sess-1'))
      // Wait for the resolved fetch to actually land in state — polling is
      // gated on `session`, not on the mock having been invoked.
      await vi.waitFor(() => expect(result.current.session?.status).toBe('running'))
      expect(mockGetSession).toHaveBeenCalledTimes(1)

      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        configurable: true,
      })

      await vi.advanceTimersByTimeAsync(6000)
      expect(mockGetSession).toHaveBeenCalledTimes(1)

      // Drive the actual hidden -> visible cycle via the real event the
      // production listener subscribes to, rather than stopping at "hidden".
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        configurable: true,
      })
      document.dispatchEvent(new Event('visibilitychange'))
      await vi.waitFor(() => expect(mockGetSession).toHaveBeenCalledTimes(2))

      // And prove normal interval polling resumed too, not just the one-off
      // resume fetch.
      await vi.advanceTimersByTimeAsync(3000)
      expect(mockGetSession).toHaveBeenCalledTimes(3)
    })

    it('stops polling once a running session actually transitions to terminal while mounted', async () => {
      mockGetSession.mockResolvedValue(makeSession({ status: 'running' }) as never)

      const { result } = renderHook(() => useSessionData('sess-1'))
      await vi.waitFor(() => expect(result.current.session?.status).toBe('running'))
      expect(mockGetSession).toHaveBeenCalledTimes(1)

      // Drive the real running -> terminal transition: the next poll tick
      // resolves with a terminal status while the hook is still mounted.
      mockGetSession.mockResolvedValue(makeSession({ status: 'completed' }) as never)
      await vi.advanceTimersByTimeAsync(3000)
      await vi.waitFor(() => expect(result.current.session?.status).toBe('completed'))
      expect(mockGetSession).toHaveBeenCalledTimes(2)

      // Now prove polling actually stopped, rather than merely not having
      // started: further timer advances must not issue another request.
      await vi.advanceTimersByTimeAsync(9000)
      expect(mockGetSession).toHaveBeenCalledTimes(2)
    })
  })
})
