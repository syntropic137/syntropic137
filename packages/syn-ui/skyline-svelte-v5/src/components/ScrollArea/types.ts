import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'
import type { ScrollAreaContract } from '@syn137/skyline-core/contracts'

/**
 * Scroll Area (ScrollAreaContract): wide content that scrolls inside its own
 * box (chip rows on a phone, mapping tables, code). Thin token-coloured
 * scrollbars, edges that fade while more content lies that way, and keyboard
 * scrolling: the box takes focus when it overflows. Give it an `aria-label`
 * so that focus stop has a name.
 */
export interface ScrollAreaProps extends ScrollAreaContract, Omit<HTMLAttributes<HTMLDivElement>, keyof ScrollAreaContract | 'children'> {
  /** CSS max-height for vertical scrolling, e.g. "20rem". */
  maxHeight?: string
  /** Hide the scrollbar (chip rows); fades still show. */
  hideScrollbar?: boolean
  children?: Snippet
}
