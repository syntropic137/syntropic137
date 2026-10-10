import type { HTMLAttributes } from 'svelte/elements'

/**
 * Skeleton (CompDisplay; no upstream contract yet): loading placeholders.
 *
 * - `lines={3}` draws the canvas stack: a 14px title at 70%, then 10px
 *   lines at 100% and 85%.
 * - `variant="block"` with `width` / `height` stands in for a chart, card or row.
 *
 * Skeletons are hidden from assistive tech. Pass `label` ("Loading
 * executions") to announce the loading state once, as a status.
 */
export type SkeletonVariant = 'title' | 'text' | 'block' | 'circle'

export interface SkeletonProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  variant?: SkeletonVariant
  /** Draw a stack of lines (first one a title). */
  lines?: number
  /** CSS length, e.g. "70%" or "12rem". */
  width?: string
  height?: string
  label?: string
}
