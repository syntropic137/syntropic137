import type { Verdict } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface VerdictSparklineProps extends Omit<HTMLAttributes<HTMLSpanElement>, 'children'> {
  /** Verdicts, oldest first. */
  verdicts: readonly Verdict[]
}
