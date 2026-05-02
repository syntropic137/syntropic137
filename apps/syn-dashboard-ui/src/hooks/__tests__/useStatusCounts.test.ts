import { describe, expect, it } from 'vitest'
import { renderHook } from '@testing-library/react'
import type { SessionSummary } from '../../types'
import { useStatusCounts } from '../useStatusCounts'

const session = (id: string, status: string): SessionSummary =>
  ({
    id,
    status,
    started_at: '2026-04-01T00:00:00Z',
    workflow_id: 'wf-1',
  }) as SessionSummary

describe('useStatusCounts', () => {
  it('returns empty object for empty list', () => {
    const { result } = renderHook(() => useStatusCounts([]))
    expect(result.current).toEqual({})
  })

  it('counts each status', () => {
    const sessions = [
      session('a', 'running'),
      session('b', 'running'),
      session('c', 'completed'),
      session('d', 'failed'),
    ]
    const { result } = renderHook(() => useStatusCounts(sessions))
    expect(result.current).toEqual({ running: 2, completed: 1, failed: 1 })
  })

  it('memoises identity across re-renders with same input', () => {
    const sessions = [session('a', 'running')]
    const { result, rerender } = renderHook(({ s }) => useStatusCounts(s), {
      initialProps: { s: sessions },
    })
    const first = result.current
    rerender({ s: sessions })
    expect(result.current).toBe(first)
  })
})
