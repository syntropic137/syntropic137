import type { HTMLAttributes } from 'svelte/elements'
import type { SeparatorContract } from '@syn137/skyline-core/contracts'

/**
 * Separator (SeparatorContract): group rules in lists. Decorative by
 * default (role none); pass `decorative={false}` when it separates
 * content a screen reader should know about.
 */
export interface SeparatorProps extends SeparatorContract, Omit<HTMLAttributes<HTMLDivElement>, keyof SeparatorContract | 'children'> {
  /** `divider` is the quieter row divider; `border` the card hairline. */
  weight?: 'border' | 'divider'
}
