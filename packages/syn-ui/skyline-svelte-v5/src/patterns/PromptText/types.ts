import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'

export interface PromptTextProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  /** Prompt or task text: the Markdown subset parsePrompt() reads. */
  text: string | null | undefined
  /** Fold to about this many lines with a Show more toggle; 0 never folds (default). */
  clampLines?: number
  /** Toggle labels while folded and while open. */
  moreLabel?: string
  lessLabel?: string
  /** Renders a `$ARGUMENTS` / `{{task}}` slot line; default is the name in mono. */
  argument?: Snippet<[string]>
}
