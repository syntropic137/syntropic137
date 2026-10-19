import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'

/**
 * Empty State (CompDisplay; no upstream contract yet): every list and chart
 * says what is missing and what to do. "No evals tagged case:x" / "Launch
 * the suite with scripts/eval_suite.py, or clear the filter." / Clear filter.
 */
export interface EmptyStateProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children' | 'title'> {
  title: string
  description?: string
  icon?: Snippet
  /** Usually one secondary Button. */
  action?: Snippet
  /** Heading level for the title, so it fits the page outline. */
  level?: 2 | 3 | 4
  /** Drop the dashed frame when the empty state sits inside a card. */
  bare?: boolean
  children?: Snippet
}
