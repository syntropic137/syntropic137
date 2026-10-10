/**
 * Example states of the Hero City for /dev/patterns: the Landing hero on
 * desktop (26 x 11) and phone (16 x 8), with the board's live, failed and
 * errored blocks. Sample data (sampleHeroCityDays), not real runs.
 */
import { sampleHeroCityDays, HERO_CITY_SAMPLE_SESSIONS } from '@syn137/skyline-core/geometry'
import type { HeroCityProps } from '@syn137/skyline-core/patterns'

export interface HeroCityExample {
  name: string
  props: HeroCityProps
}

const END = '2026-10-08'

export const HERO_CITY_EXAMPLES: readonly HeroCityExample[] = [
  {
    name: 'Hero, desktop',
    props: {
      days: sampleHeroCityDays(26, 11, END),
      maxSessions: HERO_CITY_SAMPLE_SESSIONS,
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
      days: sampleHeroCityDays(16, 8, END),
      maxSessions: HERO_CITY_SAMPLE_SESSIONS,
      cols: 16,
      rows: 8,
      cell: 30,
      live: [90, 101, 118],
      failed: [52],
      errored: [77],
    },
  },
]
