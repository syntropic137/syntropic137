// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Clock } from './clock.svelte'

describe('Clock', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('does not tick until held, ticks once a second while held, stops when the last holder releases', () => {
    vi.setSystemTime(1_000_000)
    const c = new Clock(1000)
    const t0 = c.now
    vi.advanceTimersByTime(5000)
    expect(c.now).toBe(t0)
    expect(c.ticking).toBe(false)

    const releaseA = c.hold()
    const releaseB = c.hold()
    expect(c.ticking).toBe(true)
    vi.advanceTimersByTime(3000)
    expect(c.now).toBe(1_000_000 + 5000 + 3000)

    releaseA()
    releaseA() // double release is harmless
    expect(c.ticking).toBe(true)
    vi.advanceTimersByTime(1000)
    expect(c.now).toBe(1_000_000 + 9000)

    releaseB()
    expect(c.ticking).toBe(false)
    const frozen = c.now
    vi.advanceTimersByTime(5000)
    expect(c.now).toBe(frozen)
  })
})
