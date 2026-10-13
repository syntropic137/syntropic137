import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'

/**
 * Card (CompDisplay board; no upstream contract yet). Three levels: the
 * header card with a glow, the standard card, and the raised card.
 * `selected` adds the accent edge and glow; `interactive` adds hover and
 * focus for clickable cards; `href` renders the whole card as a link.
 */
export type CardVariant = 'standard' | 'header' | 'raised'
export type CardPadding = 'none' | 'sm' | 'md' | 'lg'

export interface CardProps extends Omit<HTMLAttributes<HTMLElement>, 'children'> {
  variant?: CardVariant
  padding?: CardPadding
  interactive?: boolean
  selected?: boolean
  href?: string
  /** Host element when not a link. */
  as?: 'div' | 'section' | 'article' | 'li' | 'aside'
  children?: Snippet
}
