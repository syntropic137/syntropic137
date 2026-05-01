import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useActivityStream, __resetActivityStreamForTests } from '../useActivityStream'
import type { SSEEventFrame } from '../../types'

class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  onopen: ((ev: Event) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  onmessage: ((ev: MessageEvent) => void) | null = null
  readyState = 0
  closed = false

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  close() {
    this.closed = true
  }

  simulateOpen() {
    this.readyState = 1
    this.onopen?.(new Event('open'))
  }

  simulateMessage(frame: SSEEventFrame) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(frame) }))
  }

  simulateError() {
    this.onerror?.(new Event('error'))
  }
}

vi.mock('../../api/client', () => ({
  API_BASE: '/api/v1',
}))

const makeFrame = (overrides?: Partial<SSEEventFrame>): SSEEventFrame => ({
  type: 'event',
  event_type: 'SessionStarted',
  execution_id: null,
  data: {},
  timestamp: '2026-04-18T00:00:00Z',
  ...overrides,
})

describe('useActivityStream', () => {
  beforeEach(() => {
    MockEventSource.instances = []
    vi.stubGlobal('EventSource', MockEventSource)
    __resetActivityStreamForTests()
  })

  afterEach(() => {
    __resetActivityStreamForTests()
    vi.unstubAllGlobals()
  })

  it('opens a single EventSource on first mount', () => {
    renderHook(() => useActivityStream())
    expect(MockEventSource.instances).toHaveLength(1)
    expect(MockEventSource.instances[0].url).toBe('/api/v1/sse/activity')
  })

  it('multiplexes a single EventSource across multiple consumers', () => {
    renderHook(() => useActivityStream())
    renderHook(() => useActivityStream())
    renderHook(() => useActivityStream())
    expect(MockEventSource.instances).toHaveLength(1)
  })

  it('reflects the open state in connected', () => {
    const { result } = renderHook(() => useActivityStream())
    expect(result.current.connected).toBe(false)

    act(() => {
      MockEventSource.instances[0].simulateOpen()
    })

    expect(result.current.connected).toBe(true)
  })

  it('dispatches frames to every subscriber', () => {
    const a = vi.fn()
    const b = vi.fn()
    renderHook(() => useActivityStream({ onEvent: a }))
    renderHook(() => useActivityStream({ onEvent: b }))

    const frame = makeFrame({ event_type: 'SessionStarted' })
    act(() => {
      MockEventSource.instances[0].simulateMessage(frame)
    })

    expect(a).toHaveBeenCalledWith(frame)
    expect(b).toHaveBeenCalledWith(frame)
  })

  it('respects the per-subscriber filter', () => {
    const sessionsOnly = vi.fn()
    const gitOnly = vi.fn()
    renderHook(() =>
      useActivityStream({
        onEvent: sessionsOnly,
        filter: (t) => t.startsWith('Session'),
      }),
    )
    renderHook(() =>
      useActivityStream({
        onEvent: gitOnly,
        filter: (t) => t.startsWith('git_'),
      }),
    )

    act(() => {
      MockEventSource.instances[0].simulateMessage(makeFrame({ event_type: 'SessionStarted' }))
      MockEventSource.instances[0].simulateMessage(makeFrame({ event_type: 'git_commit' }))
    })

    expect(sessionsOnly).toHaveBeenCalledTimes(1)
    expect(gitOnly).toHaveBeenCalledTimes(1)
  })

  it('updates lastEventAt when a frame arrives', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-18T12:00:00Z'))
    const { result } = renderHook(() => useActivityStream())

    expect(result.current.lastEventAt).toBeNull()
    act(() => {
      MockEventSource.instances[0].simulateMessage(makeFrame())
    })
    expect(result.current.lastEventAt).toBe(new Date('2026-04-18T12:00:00Z').getTime())
    vi.useRealTimers()
  })

  it('reports disconnected on error', () => {
    const { result } = renderHook(() => useActivityStream())

    act(() => {
      MockEventSource.instances[0].simulateOpen()
    })
    expect(result.current.connected).toBe(true)

    act(() => {
      MockEventSource.instances[0].simulateError()
    })
    expect(result.current.connected).toBe(false)
  })

  it('closes the underlying EventSource only when the last consumer unmounts', () => {
    const a = renderHook(() => useActivityStream())
    const b = renderHook(() => useActivityStream())
    const source = MockEventSource.instances[0]
    expect(source.closed).toBe(false)

    a.unmount()
    expect(source.closed).toBe(false)

    b.unmount()
    expect(source.closed).toBe(true)
  })

  it('ignores malformed frames without crashing', () => {
    renderHook(() => useActivityStream())
    expect(() => {
      act(() => {
        MockEventSource.instances[0].onmessage?.(
          new MessageEvent('message', { data: 'not json' }),
        )
      })
    }).not.toThrow()
  })
})
