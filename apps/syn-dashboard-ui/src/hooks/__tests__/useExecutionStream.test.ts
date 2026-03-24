import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useExecutionStream, type SSEEventFrame } from '../useExecutionStream'

// Mock EventSource
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

  // Test helpers
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

describe('useExecutionStream', () => {
  beforeEach(() => {
    MockEventSource.instances = []
    vi.stubGlobal('EventSource', MockEventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const makeFrame = (overrides?: Partial<SSEEventFrame>): SSEEventFrame => ({
    type: 'event',
    event_type: 'PhaseStarted',
    execution_id: 'exec-1',
    data: {},
    timestamp: '2026-03-23T00:00:00Z',
    ...overrides,
  })

  it('does not connect when executionId is undefined', () => {
    renderHook(() => useExecutionStream(undefined))
    expect(MockEventSource.instances).toHaveLength(0)
  })

  it('connects to the correct SSE URL', () => {
    renderHook(() => useExecutionStream('exec-1'))
    expect(MockEventSource.instances).toHaveLength(1)
    expect(MockEventSource.instances[0].url).toBe('/api/v1/sse/executions/exec-1')
  })

  it('sets isConnected on open', () => {
    const { result } = renderHook(() => useExecutionStream('exec-1'))
    expect(result.current.isConnected).toBe(false)

    act(() => {
      MockEventSource.instances[0].simulateOpen()
    })
    expect(result.current.isConnected).toBe(true)
  })

  it('accumulates events', () => {
    const { result } = renderHook(() => useExecutionStream('exec-1'))
    const frame1 = makeFrame({ event_type: 'PhaseStarted' })
    const frame2 = makeFrame({ event_type: 'PhaseCompleted' })

    act(() => {
      MockEventSource.instances[0].simulateOpen()
      MockEventSource.instances[0].simulateMessage(frame1)
      MockEventSource.instances[0].simulateMessage(frame2)
    })

    expect(result.current.events).toHaveLength(2)
    expect(result.current.latestEvent).toEqual(frame2)
  })

  it('calls onEvent callback for each frame', () => {
    const onEvent = vi.fn()
    renderHook(() => useExecutionStream('exec-1', { onEvent }))
    const frame = makeFrame()

    act(() => {
      MockEventSource.instances[0].simulateMessage(frame)
    })

    expect(onEvent).toHaveBeenCalledWith(frame)
  })

  it('closes on terminal frame', () => {
    const { result } = renderHook(() => useExecutionStream('exec-1'))
    const terminalFrame = makeFrame({ type: 'terminal', event_type: 'WorkflowCompleted' })

    act(() => {
      MockEventSource.instances[0].simulateOpen()
      MockEventSource.instances[0].simulateMessage(terminalFrame)
    })

    expect(MockEventSource.instances[0].closed).toBe(true)
    expect(result.current.isConnected).toBe(false)
  })

  it('sets isConnected false on error', () => {
    const { result } = renderHook(() => useExecutionStream('exec-1'))

    act(() => {
      MockEventSource.instances[0].simulateOpen()
    })
    expect(result.current.isConnected).toBe(true)

    act(() => {
      MockEventSource.instances[0].simulateError()
    })
    expect(result.current.isConnected).toBe(false)
  })

  it('closes EventSource on unmount', () => {
    const { unmount } = renderHook(() => useExecutionStream('exec-1'))
    const source = MockEventSource.instances[0]
    expect(source.closed).toBe(false)

    unmount()
    expect(source.closed).toBe(true)
  })

  it('ignores malformed messages', () => {
    const { result } = renderHook(() => useExecutionStream('exec-1'))

    act(() => {
      MockEventSource.instances[0].onmessage?.(
        new MessageEvent('message', { data: 'not json' }),
      )
    })

    expect(result.current.events).toHaveLength(0)
  })
})
