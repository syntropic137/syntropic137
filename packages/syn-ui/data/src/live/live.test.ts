import { describe, expect, it, vi } from 'vitest'
import type { SSEEventFrame } from '../types'
import { type EventSourceLike, LiveHub, createFrameBatcher } from './index'

/** A manual scheduler: tick() runs the pending frame. */
function manualScheduler() {
  let pending: Array<() => void> = []
  return {
    schedule: (run: () => void) => {
      pending.push(run)
      return () => {
        pending = pending.filter((p) => p !== run)
      }
    },
    tick: () => {
      const due = pending
      pending = []
      for (const p of due) p()
    },
  }
}

class FakeSource implements EventSourceLike {
  onopen: EventSourceLike['onopen'] = null
  onerror: EventSourceLike['onerror'] = null
  onmessage: EventSourceLike['onmessage'] = null
  readyState = 0
  closed = false
  constructor(readonly url: string) {}
  close() {
    this.closed = true
  }
  emit(frame: Partial<SSEEventFrame>) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify({ type: 'event', data: {}, execution_id: null, timestamp: '', event_type: 'x', ...frame }) }))
  }
}

describe('frame batcher', () => {
  it('delivers a burst once per frame', () => {
    const s = manualScheduler()
    const deliver = vi.fn()
    const b = createFrameBatcher<number>(deliver, s.schedule)
    b.push(1)
    b.push(2)
    b.push(3)
    expect(deliver).not.toHaveBeenCalled()
    s.tick()
    expect(deliver).toHaveBeenCalledExactlyOnceWith([1, 2, 3])
    b.push(4)
    b.cancel()
    s.tick()
    expect(deliver).toHaveBeenCalledTimes(1)
  })
})

describe('LiveHub', () => {
  it('shares one source per URL, filters and batches per subscriber, closes on last unsubscribe', () => {
    const s = manualScheduler()
    const sources: FakeSource[] = []
    const hub = new LiveHub({ createSource: (url) => (sources.push(new FakeSource(url)), sources.at(-1)!), schedule: s.schedule, fixtures: () => false })
    const a = vi.fn()
    const b = vi.fn()
    const states: string[] = []
    const offA = hub.subscribe('/sse/activity', { onFrames: a, onState: (st) => states.push(st) })
    const offB = hub.subscribe('/sse/activity', { onFrames: b, filter: (t) => t === 'phase_completed' })
    expect(sources).toHaveLength(1)
    const src = sources[0]!
    src.onopen?.(new Event('open'))
    expect(hub.state('/sse/activity')).toBe('open')
    expect(states).toEqual(['connecting', 'open'])
    src.emit({ event_type: 'phase_started' })
    src.emit({ event_type: 'phase_completed' })
    src.onmessage?.(new MessageEvent('message', { data: 'not json' }))
    s.tick()
    expect(a.mock.calls[0]![0]).toHaveLength(2)
    expect(b.mock.calls[0]![0].map((f: SSEEventFrame) => f.event_type)).toEqual(['phase_completed'])
    offA()
    expect(src.closed).toBe(false)
    offB()
    expect(src.closed).toBe(true)
    expect(hub.state('/sse/activity')).toBe('closed')
  })
  it('does not connect in fixtures mode', () => {
    const create = vi.fn()
    const hub = new LiveHub({ createSource: create, fixtures: () => true })
    const states: string[] = []
    hub.subscribe('/sse/activity', { onState: (st) => states.push(st) })
    expect(create).not.toHaveBeenCalled()
    expect(states).toEqual(['fixtures'])
  })
})

describe('LiveHub reconnects (#1924)', () => {
  const setup = () => {
    vi.useFakeTimers()
    const s = manualScheduler()
    const sources: FakeSource[] = []
    const hub = new LiveHub({
      createSource: (url) => (sources.push(new FakeSource(url)), sources.at(-1)!),
      schedule: s.schedule,
      fixtures: () => false,
      reconnectDelayMs: (n) => 1000 * 2 ** n,
    })
    return { hub, sources }
  }
  const open = (src: FakeSource) => {
    src.readyState = 1
    src.onopen?.(new Event('open'))
  }
  const giveUp = (src: FakeSource) => {
    src.readyState = 2 // an HTTP error on a retry: EventSource stops for good
    src.onerror?.(new Event('error'))
  }

  it('reopens a source the browser closed, with backoff, and tells subscribers they missed frames', () => {
    const { hub, sources } = setup()
    try {
      const onReconnect = vi.fn()
      const off = hub.subscribe('/sse/activity', { onReconnect })
      open(sources[0]!)
      expect(onReconnect).not.toHaveBeenCalled() // the first open is not a reconnect
      giveUp(sources[0]!)
      expect(sources[0]!.closed).toBe(true)
      expect(hub.state('/sse/activity')).toBe('closed')
      vi.advanceTimersByTime(999)
      expect(sources).toHaveLength(1)
      vi.advanceTimersByTime(1)
      expect(sources).toHaveLength(2)
      expect(hub.state('/sse/activity')).toBe('connecting')
      giveUp(sources[1]!) // still down: wait doubles
      vi.advanceTimersByTime(1999)
      expect(sources).toHaveLength(2)
      vi.advanceTimersByTime(1)
      expect(sources).toHaveLength(3)
      open(sources[2]!)
      expect(hub.state('/sse/activity')).toBe('open')
      expect(onReconnect).toHaveBeenCalledOnce()
      giveUp(sources[2]!) // a successful open resets the backoff
      vi.advanceTimersByTime(1000)
      expect(sources).toHaveLength(4)
      off()
    } finally {
      vi.useRealTimers()
    }
  })

  it("signals a reconnect after the browser's own retry too", () => {
    const { hub, sources } = setup()
    try {
      const onReconnect = vi.fn()
      hub.subscribe('/sse/activity', { onReconnect })
      open(sources[0]!)
      sources[0]!.readyState = 0 // network drop: EventSource retries on its own
      sources[0]!.onerror?.(new Event('error'))
      expect(hub.state('/sse/activity')).toBe('connecting')
      expect(sources).toHaveLength(1)
      open(sources[0]!)
      expect(onReconnect).toHaveBeenCalledOnce()
    } finally {
      vi.useRealTimers()
    }
  })

  it('signals a reconnect when the first connection never opened', () => {
    const { hub, sources } = setup()
    try {
      const onReconnect = vi.fn()
      hub.subscribe('/sse/activity', { onReconnect })
      giveUp(sources[0]!) // the page loaded over REST but the stream failed at once
      vi.advanceTimersByTime(1000)
      open(sources[1]!)
      expect(onReconnect).toHaveBeenCalledOnce()
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not reopen once the last subscriber leaves', () => {
    const { hub, sources } = setup()
    try {
      const off = hub.subscribe('/sse/activity', {})
      open(sources[0]!)
      giveUp(sources[0]!)
      off()
      vi.advanceTimersByTime(60_000)
      expect(sources).toHaveLength(1)
    } finally {
      vi.useRealTimers()
    }
  })
})
