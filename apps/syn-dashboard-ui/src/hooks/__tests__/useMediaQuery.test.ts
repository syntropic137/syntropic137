/**
 * Tests for useMediaQuery + useIsMobile.
 */

import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useIsMobile, useMediaQuery } from '../useMediaQuery'

type Listener = (e: MediaQueryListEvent) => void

interface MockMQL {
  matches: boolean
  media: string
  addEventListener: (type: 'change', listener: Listener) => void
  removeEventListener: (type: 'change', listener: Listener) => void
  // Test helper:
  fire: (matches: boolean) => void
}

function createMatchMedia(initial: Record<string, boolean>): {
  matchMedia: (q: string) => MockMQL
  fire: (q: string, matches: boolean) => void
} {
  const listeners = new Map<string, Set<Listener>>()
  const states = new Map<string, boolean>(Object.entries(initial))

  function matchMedia(query: string): MockMQL {
    if (!listeners.has(query)) listeners.set(query, new Set())
    const set = listeners.get(query)!
    return {
      matches: states.get(query) ?? false,
      media: query,
      addEventListener: (_type, l) => set.add(l),
      removeEventListener: (_type, l) => set.delete(l),
      fire: (matches: boolean) => {
        states.set(query, matches)
        for (const l of set) l({ matches } as MediaQueryListEvent)
      },
    }
  }

  function fire(query: string, matches: boolean) {
    states.set(query, matches)
    const set = listeners.get(query)
    if (!set) return
    for (const l of set) l({ matches } as MediaQueryListEvent)
  }

  return { matchMedia, fire }
}

describe('useMediaQuery', () => {
  let mock: ReturnType<typeof createMatchMedia>

  beforeEach(() => {
    mock = createMatchMedia({ '(min-width: 768px)': true })
    vi.stubGlobal('matchMedia', mock.matchMedia)
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: mock.matchMedia,
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns initial match state', () => {
    const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'))
    expect(result.current).toBe(true)
  })

  it('updates when the media query changes', () => {
    const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'))
    expect(result.current).toBe(true)
    act(() => mock.fire('(min-width: 768px)', false))
    expect(result.current).toBe(false)
  })

  it('useIsMobile returns true when md does not match', () => {
    mock = createMatchMedia({ '(min-width: 768px)': false })
    Object.defineProperty(window, 'matchMedia', { configurable: true, value: mock.matchMedia })
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(true)
  })
})
