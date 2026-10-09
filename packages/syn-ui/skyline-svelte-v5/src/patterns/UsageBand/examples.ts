/** Example states of the Usage Band for /dev/patterns: the UsageMeter and Landing boards (sample data). */
import type { UsageBandProps } from './types'

export interface UsageBandExample {
  name: string
  props: UsageBandProps
}

export const USAGE_BAND_EXAMPLES: readonly UsageBandExample[] = [
  { name: 'Usage Meter band', props: { tokens: { cacheRead: 144_128, cacheWrite: 0, output: 1_945, input: 29_924 }, rates: { cacheRead: '0.1× rate' } } },
  {
    name: 'Landing, run #142',
    props: { tokens: { cacheRead: 582_400, cacheWrite: 201_600, output: 235_200, input: 100_800 }, shape: 'flat', legend: 'compact' },
  },
  { name: 'Nothing recorded', props: { tokens: { cacheRead: 0, cacheWrite: 0, output: 0, input: 0 } } },
]
