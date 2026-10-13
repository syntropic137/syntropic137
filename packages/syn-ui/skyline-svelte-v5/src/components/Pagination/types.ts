import type { HTMLAttributes } from 'svelte/elements'
import type { PaginationContract } from '@syn137/skyline-core/contracts'

/**
 * Pagination (PaginationContract). CompDisplay: every list ends with the
 * count shown and the two buttons ("Showing 12 of 27 workflows · Previous ·
 * 1 / 3 · Next"). `mode="pages"` adds numbered pages with gaps, using
 * `siblingCount`. `bind:page` or `page` + `onPageChange`.
 */
export interface PaginationProps extends Omit<PaginationContract, 'count' | 'perPage'>, Omit<HTMLAttributes<HTMLElement>, keyof PaginationContract | 'children'> {
  /** Skyline: number of pages. Upstream takes an item `count` and `perPage` instead. */
  pageCount: number
  /** "Showing 12 of 27 workflows". */
  summary?: string
  mode?: 'compact' | 'pages'
  previousLabel?: string
  nextLabel?: string
}
