/**
 * Example states of the S Mark for /dev/patterns (and a future Storybook):
 * nav, footer and hero sizes from the Landing board.
 */
import type { SMarkProps } from '@syn137/skyline-core/patterns'

export interface SMarkExample {
  name: string
  props: SMarkProps
}

export const S_MARK_EXAMPLES: readonly SMarkExample[] = [
  { name: 'Nav (26px)', props: { size: 26 } },
  { name: 'Footer (22px), decorative', props: { size: 22, label: '' } },
  { name: 'Sign-off (150px)', props: { size: 150 } },
  { name: 'Hero, dropping in', props: { size: 120, animate: true, label: 'The Syntropic137 S, built from cubes' } },
]
