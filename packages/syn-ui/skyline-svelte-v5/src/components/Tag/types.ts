import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'

/**
 * Tag (CompDisplay "Tag and chips"; no upstream contract yet). Small mono
 * labels for slugs, IDs, types, skills and agents.
 *
 * | Canvas            | Props                         |
 * |-------------------|-------------------------------|
 * | tag, clickable    | `variant="accent"` + `href` or `onclick` |
 * | type              | `variant="outline"`           |
 * | skill             | `variant="skill"`             |
 * | agent             | `variant="agent" agent="claude"` |
 * | missing value     | `variant="dashed"`            |
 * | removable filter  | `onremove`                    |
 */
export type TagVariant = 'accent' | 'outline' | 'skill' | 'agent' | 'dashed'
export type TagAgent = 'claude' | 'codex' | 'other'

export interface TagProps extends Omit<HTMLAttributes<HTMLElement>, 'children'> {
  variant?: TagVariant
  /** Dot colour for `variant="agent"`. */
  agent?: TagAgent
  /** Renders as a link. */
  href?: string
  /** Renders as a button. */
  onclick?: (e: MouseEvent) => void
  /** Renders as a filter chip that removes itself; the whole chip is the button. */
  onremove?: () => void
  /** Accessible name for the remove action. Defaults to "Remove filter <text>" (visually hidden prefix). */
  removeLabel?: string
  icon?: Snippet
  children?: Snippet
}
