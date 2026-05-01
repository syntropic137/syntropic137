import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { createElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { useSessionList } from '../useSessionList'

vi.mock('../../api/sessions', () => ({
  listSessions: vi.fn(),
}))

vi.mock('../useActivityStream', () => ({
  useActivityStream: vi.fn(() => ({ connected: true, lastEventAt: null })),
}))

import { listSessions } from '../../api/sessions'

const mockListSessions = vi.mocked(listSessions)

const makeSessionSummary = (overrides = {}) => ({
  id: 'sess-1',
  status: 'completed',
  started_at: '2026-04-01T00:00:00Z',
  workflow_id: 'wf-1',
  total_tokens: 500,
  ...overrides,
})

function wrapper({ children }: { children: React.ReactNode }) {
  return createElement(MemoryRouter, null, children)
}

describe('useSessionList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('unwraps paginated { sessions, total } response into sessions array', async () => {
    const session = makeSessionSummary()
    mockListSessions.mockResolvedValue({ sessions: [session], total: 1 })

    const { result } = renderHook(() => useSessionList(), { wrapper })

    expect(result.current.loading).toBe(true)

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.sessions).toEqual([session])
    expect(result.current.sessions).toHaveLength(1)
    expect(result.current.sessions[0].id).toBe('sess-1')
  })

  it('returns empty array when API returns no sessions', async () => {
    mockListSessions.mockResolvedValue({ sessions: [], total: 0 })

    const { result } = renderHook(() => useSessionList(), { wrapper })

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.sessions).toEqual([])
    expect(result.current.filteredSessions).toEqual([])
  })

  it('handles fetch error gracefully', async () => {
    mockListSessions.mockRejectedValue(new Error('Network error'))

    const { result } = renderHook(() => useSessionList(), { wrapper })

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.sessions).toEqual([])
  })

  it('filters sessions by search query on id and workflow_id', async () => {
    const sessions = [
      makeSessionSummary({ id: 'sess-alpha', workflow_id: 'wf-deploy' }),
      makeSessionSummary({ id: 'sess-beta', workflow_id: 'wf-test' }),
    ]
    mockListSessions.mockResolvedValue({ sessions, total: 2 })

    const { result } = renderHook(() => useSessionList(), { wrapper })

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    result.current.setSearchQuery('alpha')

    await waitFor(() => {
      expect(result.current.filteredSessions).toHaveLength(1)
    })

    expect(result.current.filteredSessions[0].id).toBe('sess-alpha')
  })
})
