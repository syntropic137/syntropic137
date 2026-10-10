/**
 * Example states of the Iso City for /dev/patterns: the Landing hero on
 * desktop (26 x 11) and phone (16 x 8), with the board's live, failed and
 * errored blocks. Sample data (sampleCityDays), not real runs.
 */
import { sampleCityDays, SAMPLE_SESSIONS } from '@syn137/skyline-core/geometry'
import type { IsoCityProps } from '@syn137/skyline-core/patterns'

export interface IsoCityExample {
  name: string
  props: IsoCityProps
}

const END = '2026-10-08'

export const ISO_CITY_EXAMPLES: readonly IsoCityExample[] = [
  {
    name: 'Hero, desktop',
    props: {
      days: sampleCityDays(26, 11, END),
      maxSessions: SAMPLE_SESSIONS,
      live: [150, 171, 199, 222],
      failed: [88, 260],
      errored: [141],
      animate: true,
      drift: true,
      label: 'A city of blocks, one per day of agent runs, with the Syntropic137 S rising from the middle',
    },
  },
  {
    name: 'Hero, phone',
    props: {
      days: sampleCityDays(16, 8, END),
      maxSessions: SAMPLE_SESSIONS,
      cols: 16,
      rows: 8,
      cell: 30,
      live: [90, 101, 118],
      failed: [52],
      errored: [77],
    },
  },
]
