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
