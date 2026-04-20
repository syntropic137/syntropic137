import { describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { createElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { timeWindowToStartedAfter, useFilterUrlState } from '../useFilterUrlState'

function makeWrapper(initialEntries: string[] = ['/']) {
  return ({ children }: { children: React.ReactNode }) =>
    createElement(MemoryRouter, { initialEntries }, children)
}

describe('useFilterUrlState', () => {
  it('parses status and timeWindow from initial URL', () => {
    const { result } = renderHook(() => useFilterUrlState(), {
      wrapper: makeWrapper(['/?status=running,failed&timeWindow=7d']),
    })

    expect(result.current.selectedStatuses.has('running')).toBe(true)
    expect(result.current.selectedStatuses.has('failed')).toBe(true)
    expect(result.current.selectedStatuses.size).toBe(2)
    expect(result.current.timeWindow).toBe('7d')
  })

  it('defaults timeWindow to 24h when missing', () => {
    const { result } = renderHook(() => useFilterUrlState(), {
      wrapper: makeWrapper(['/']),
    })

    expect(result.current.timeWindow).toBe('24h')
    expect(result.current.selectedStatuses.size).toBe(0)
  })

  it('toggleStatus adds and removes statuses', () => {
    const { result } = renderHook(() => useFilterUrlState(), {
      wrapper: makeWrapper(['/']),
    })

    act(() => result.current.toggleStatus('running'))
    expect(result.current.selectedStatuses.has('running')).toBe(true)

    act(() => result.current.toggleStatus('running'))
    expect(result.current.selectedStatuses.has('running')).toBe(false)
  })

  it('clearAll removes status and timeWindow', () => {
    const { result } = renderHook(() => useFilterUrlState(), {
      wrapper: makeWrapper(['/?status=running&timeWindow=7d']),
    })

    act(() => result.current.clearAll())
    expect(result.current.selectedStatuses.size).toBe(0)
    expect(result.current.timeWindow).toBe('24h')
  })

  it('rejects invalid timeWindow values', () => {
    const { result } = renderHook(() => useFilterUrlState(), {
      wrapper: makeWrapper(['/?timeWindow=bogus']),
    })

    expect(result.current.timeWindow).toBe('24h')
  })
})

describe('timeWindowToStartedAfter', () => {
  const now = new Date('2026-04-19T12:00:00.000Z')

  it('returns ISO bound for 15m', () => {
    expect(timeWindowToStartedAfter('15m', now)).toBe('2026-04-19T11:45:00.000Z')
  })

  it('returns ISO bound for 1h', () => {
    expect(timeWindowToStartedAfter('1h', now)).toBe('2026-04-19T11:00:00.000Z')
  })

  it('returns ISO bound for 24h', () => {
    expect(timeWindowToStartedAfter('24h', now)).toBe('2026-04-18T12:00:00.000Z')
  })

  it('returns ISO bound for 7d', () => {
    expect(timeWindowToStartedAfter('7d', now)).toBe('2026-04-12T12:00:00.000Z')
  })

  it('returns undefined for all', () => {
    expect(timeWindowToStartedAfter('all', now)).toBeUndefined()
  })
})
