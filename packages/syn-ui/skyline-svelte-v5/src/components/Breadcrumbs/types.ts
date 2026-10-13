import type { HTMLAttributes } from 'svelte/elements'
import type { Crumb } from '@syn137/skyline-core/patterns'

/**
 * Breadcrumbs (CompNav; no upstream contract yet). Home, each parent, then
 * the current page as a pill ("Execution 66e14f23"). Below 48rem the middle
 * hides behind an ellipsis button and only the parent and the current page
 * show, at 44px.
 *
 * `items` hrefs are used as given; the app resolves its deploy base before
 * passing them (the App Shell's Breadcrumb Trail pattern does this).
 */
export interface BreadcrumbsProps extends Omit<HTMLAttributes<HTMLElement>, 'children'> {
  items: Crumb[]
  /** Link for the home icon. Omit to drop the home step. */
  homeHref?: string
  homeLabel?: string
  /** `never` keeps every step visible on a phone too. */
  collapse?: 'auto' | 'never'
}
