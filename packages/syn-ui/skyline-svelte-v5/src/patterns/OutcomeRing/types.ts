import type { OutcomeCounts } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface OutcomeRingProps extends OutcomeCounts, Omit<HTMLAttributes<HTMLElement>, 'children'> {
  /** What is counted, for the heading and the accessible name (default "executions"). */
  noun?: string
  /** Show the heading and the legend beside the ring (Main board card). Default true. */
  legend?: boolean
  /** Ring size in px (default 120). */
  size?: number
}
