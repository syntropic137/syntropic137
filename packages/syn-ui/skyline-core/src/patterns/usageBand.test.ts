import { describe, expect, it } from 'vitest'
import { usageBand, usageModel } from './index'

describe('usage band', () => {
  it('is the Usage Meter band, shared', () => {
    const tokens = { cacheRead: 144_128, cacheWrite: 0, output: 1_945, input: 29_924 }
    const b = usageBand({ tokens, rates: { cacheRead: '0.1× rate' } })
    const meter = usageModel({ tokens, rates: { cacheRead: '0.1× rate' }, costRows: [], costBy: 'model' })
    expect(b.series).toEqual(meter.series)
    expect(b.bandLabel).toBe(meter.bandLabel)
    expect(b.series.map((s) => s.label)).toEqual(['Cache read', 'Output', 'Input'])
    expect(usageBand({ tokens: { cacheRead: 0, cacheWrite: 0, output: 0, input: 0 } }).bandLabel).toBe('No tokens recorded')
  })
})
