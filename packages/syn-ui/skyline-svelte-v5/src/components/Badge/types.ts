import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'
import type { BadgeContract } from '@syn137/skyline-core/contracts'

/**
 * Badge (CompDisplay board). Status and verdict pills.
 *
 * Map a status with `statusSemantics()` from `@syn137/skyline-core/patterns`
 * rather than picking a variant on a screen: Completed is soft + accent,
 * Failed soft + danger, Cancelled outline + neutral.
 */
export interface BadgeProps extends BadgeContract, Omit<HTMLAttributes<HTMLSpanElement>, keyof BadgeContract | 'children'> {
  children?: Snippet
  /** Leading glyph (12px), e.g. the status check or cross. */
  icon?: Snippet
  /** A small live dot with a halo instead of an icon (Running). */
  dot?: boolean
}
