import { describe, expect, it, vi, beforeEach } from 'vitest'
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
})
