import type { Operation } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface OperationTimelineProps extends Omit<HTMLAttributes<HTMLOListElement>, 'children'> {
  /** Tool calls, oldest first, start and finish already merged. */
  operations: readonly Operation[]
  /** Lines of output shown before it folds behind "Show all" (default 8). */
  previewLines?: number
  /** Unfold every output (the screen's "Expand all"). */
  expanded?: boolean
}
