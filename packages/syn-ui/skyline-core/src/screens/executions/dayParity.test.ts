// The Skyline's "Runs →" day and the list's ?day= filter must name the same
// 24 hours (#1938, #1939), whatever zone the viewer is in. Both are UTC days
// (#1371): a viewer west of UTC sees a late-evening run under the next day.
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { dayFromMs } from '../../geometry/skyline'
import { dayBounds } from './list'

const zone = process.env.TZ
beforeAll(() => {
  process.env.TZ = 'America/Los_Angeles'
})
afterAll(() => {
  process.env.TZ = zone
})

const inBounds = (ms: number, day: string) => {
  const b = dayBounds(day)!
  return ms >= Date.parse(b.started_after) && ms <= Date.parse(b.started_before)
}

describe('Skyline day == ?day= bounds, west of UTC near midnight', () => {
  it('a run at 23:30 local is listed under the day the Skyline put it on', () => {
    const run = new Date(2026, 9, 13, 23, 30).getTime()
    expect(new Date(run).toISOString()).toBe('2026-10-14T06:30:00.000Z') // the zone took effect
    const skylineDay = dayFromMs(run)
    expect(skylineDay).toBe('2026-10-14')
    expect(inBounds(run, skylineDay)).toBe(true)
    expect(inBounds(run, '2026-10-13')).toBe(false)
  })

  it('a run just after local midnight stays on the same UTC day as the one before it', () => {
    const run = new Date(2026, 9, 14, 0, 15).getTime()
    expect(dayFromMs(run)).toBe('2026-10-14')
    expect(inBounds(run, '2026-10-14')).toBe(true)
  })
})
