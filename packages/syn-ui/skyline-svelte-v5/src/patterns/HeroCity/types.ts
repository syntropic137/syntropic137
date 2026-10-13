import type { HeroCityProps as HeroCityData } from '@syn137/skyline-core/patterns'
import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'

export interface HeroCityProps extends HeroCityData, Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  /** Skyline: drawn over the city, top centre, inside the drifting stage (the hero's S). */
  overlay?: Snippet
}
