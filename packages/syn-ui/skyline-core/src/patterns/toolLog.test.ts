import { describe, expect, it } from 'vitest'
import { tickerTiming, TOOL_LOG_PLAY_SECONDS } from './index'

describe('tool-log ticker timing (energy rule)', () => {
  it('plays the board rows for about 20 seconds, then stops', () => {
    expect(tickerTiming(8)).toEqual({ moving: true, duration: 14, iterations: 1 })
    const fast = tickerTiming(8, 0.5)
    expect(fast).toEqual({ moving: true, duration: 4, iterations: 5 })
    expect(fast.duration * fast.iterations).toBeLessThanOrEqual(TOOL_LOG_PLAY_SECONDS)
  })

  it('stays still with speed 0 or too few rows', () => {
    expect(tickerTiming(8, 0).moving).toBe(false)
    expect(tickerTiming(1).moving).toBe(false)
    expect(tickerTiming(8, Number.NaN).moving).toBe(false)
  })
})
