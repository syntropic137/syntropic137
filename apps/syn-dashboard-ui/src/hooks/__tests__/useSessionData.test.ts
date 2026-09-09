import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useSessionData } from '../useSessionData'

vi.mock('../../api/sessions', () => ({
  getSession: vi.fn(),
}))

// Controllable stand-in for the execution stream, so the two regimes can be
// told apart: connected means SSE carries this session's changes, disconnected
// means the fallback poll is the only channel (#1095).
let streamConnected = false
let streamHandler: ((frame: SSEEventFrame) => void) | undefined
let subscribedExecutionId: string | undefined
vi.mock('../useExecutionStream', () => ({
  useExecutionStream: (
    executionId: string | undefined,
    options?: { onEvent?: (frame: SSEEventFrame) => void },
  ) => {
    subscribedExecutionId = executionId
    streamHandler = options?.onEvent
    return { isConnected: executionId ? streamConnected : false }
  },
}))

import { getSession } from '../../api/sessions'
import type { SSEEventFrame } from '../../types'

const mockGetSession = vi.mocked(getSession)

/** `useLiveRecord`'s DISCONNECTED_POLL_MS. */
const FALLBACK_POLL_MS = 10_000

function frame(event_type: string, data: Record<string, unknown>): SSEEventFrame {
  return { type: 'event', event_type, execution_id: 'exec-1', data, timestamp: '' }
}

const makeSession = (overrides = {}) => ({
  session_id: 'sess-1',
  execution_id: null,
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
    streamConnected = false
    streamHandler = undefined
    subscribedExecutionId = undefined
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

  describe('fallback polling while the stream is down (#1048, #1095)', () => {
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

      await vi.advanceTimersByTimeAsync(FALLBACK_POLL_MS * 2)
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
      await vi.advanceTimersByTimeAsync(FALLBACK_POLL_MS)
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
      await vi.advanceTimersByTimeAsync(FALLBACK_POLL_MS)
      await vi.waitFor(() => expect(result.current.session?.status).toBe('completed'))
      expect(mockGetSession).toHaveBeenCalledTimes(2)

      // Now prove polling actually stopped, rather than merely not having
      // started: further timer advances must not issue another request.
      await vi.advanceTimersByTimeAsync(FALLBACK_POLL_MS * 3)
      expect(mockGetSession).toHaveBeenCalledTimes(2)
    })
  })
})

describe('useSessionData subscribes to its execution instead of polling (#1095)', () => {
  const runningSession = (overrides = {}) =>
    makeSession({
      status: 'running',
      execution_id: 'exec-1',
      completed_at: null,
      ...overrides,
    })

  beforeEach(() => {
    vi.clearAllMocks()
    streamConnected = true
    streamHandler = undefined
    subscribedExecutionId = undefined
    vi.useFakeTimers()
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
  })

  afterEach(() => {
    vi.useRealTimers()
    streamConnected = false
  })

  it("subscribes to the session's own execution channel", async () => {
    mockGetSession.mockResolvedValue(runningSession() as never)

    const { result } = renderHook(() => useSessionData('sess-1'))
    await vi.waitFor(() => expect(result.current.session?.status).toBe('running'))

    await vi.waitFor(() => expect(subscribedExecutionId).toBe('exec-1'))
    await vi.waitFor(() => expect(result.current.isConnected).toBe(true))
  })

  it('issues no interval request at all while the stream is up', async () => {
    mockGetSession.mockResolvedValue(runningSession() as never)

    const { result } = renderHook(() => useSessionData('sess-1'))
    await vi.waitFor(() => expect(result.current.session?.status).toBe('running'))

    // Initial fetch, plus one on connect: the EventSource opens after the first
    // fetch is already in flight and the stream has no replay, so the window
    // between them can only be closed by asking again.
    await vi.waitFor(() => expect(mockGetSession).toHaveBeenCalledTimes(2))

    // Ten fallback intervals on a running session with a visible tab. Before
    // this change that was ~100 seconds of 3s polling: 33 requests.
    await vi.advanceTimersByTimeAsync(FALLBACK_POLL_MS * 10)
    expect(mockGetSession).toHaveBeenCalledTimes(2)
  })

  it('refetches when this session records an operation', async () => {
    mockGetSession.mockResolvedValue(runningSession({ total_tokens: 100 }) as never)

    const { result } = renderHook(() => useSessionData('sess-1'))
    await vi.waitFor(() => expect(mockGetSession).toHaveBeenCalledTimes(2))

    mockGetSession.mockResolvedValue(runningSession({ total_tokens: 900 }) as never)
    streamHandler?.(frame('OperationRecorded', { session_id: 'sess-1', total_tokens: 800 }))

    await vi.advanceTimersByTimeAsync(500)
    await vi.waitFor(() => expect(result.current.session?.total_tokens).toBe(900))
  })

  it("ignores an operation recorded by a sibling session in the same execution", async () => {
    mockGetSession.mockResolvedValue(runningSession() as never)

    renderHook(() => useSessionData('sess-1'))
    await vi.waitFor(() => expect(mockGetSession).toHaveBeenCalledTimes(2))

    // A delegating agent's subagent shares the execution channel but changes
    // nothing on this page, so its frames must not cost a request.
    streamHandler?.(frame('OperationRecorded', { session_id: 'sess-2', total_tokens: 800 }))

    await vi.advanceTimersByTimeAsync(FALLBACK_POLL_MS)
    expect(mockGetSession).toHaveBeenCalledTimes(2)
  })

  it('refetches when this session completes', async () => {
    mockGetSession.mockResolvedValue(runningSession() as never)

    const { result } = renderHook(() => useSessionData('sess-1'))
    await vi.waitFor(() => expect(mockGetSession).toHaveBeenCalledTimes(2))

    mockGetSession.mockResolvedValue(makeSession({ execution_id: 'exec-1' }) as never)
    streamHandler?.(frame('SessionCompleted', { session_id: 'sess-1' }))

    await vi.advanceTimersByTimeAsync(500)
    await vi.waitFor(() => expect(result.current.session?.status).toBe('completed'))
  })

  it('falls back to the poll for a session that belongs to no execution', async () => {
    // A session started outside a workflow run has no per-execution channel to
    // subscribe to. That is a real gap in the stream, not a bug: the poll is
    // the only thing that can keep such a page current.
    mockGetSession.mockResolvedValue(
      makeSession({ status: 'running', execution_id: null, completed_at: null }) as never,
    )

    const { result } = renderHook(() => useSessionData('sess-1'))
    await vi.waitFor(() => expect(result.current.session?.status).toBe('running'))
    expect(subscribedExecutionId).toBeUndefined()
    expect(result.current.isConnected).toBe(false)
    expect(mockGetSession).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(FALLBACK_POLL_MS)
    expect(mockGetSession).toHaveBeenCalledTimes(2)
  })
})
