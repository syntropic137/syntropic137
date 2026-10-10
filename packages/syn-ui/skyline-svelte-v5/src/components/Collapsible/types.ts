import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'
import type { CollapsibleRootContract } from '@syn137/skyline-core/contracts'

/** Props the `trigger` snippet spreads onto its own button. */
export interface CollapsibleTriggerProps {
  'aria-expanded': boolean
  'aria-controls': string
  'data-state': 'open' | 'closed'
  disabled: boolean
  onclick: () => void
}

/**
 * Collapsible (CollapsibleRootContract): operation output, a phase prompt,
 * an artifact's outline. CompNav "collapsible": a 44px header row with a
 * chevron; the content shows under a hairline.
 *
 * Give it a `title` for the drawn header, or a `trigger` snippet to supply
 * your own control. `bind:open` or `open` + `onOpenChange`.
 */
export interface CollapsibleProps extends CollapsibleRootContract, Omit<HTMLAttributes<HTMLDivElement>, keyof CollapsibleRootContract | 'children' | 'title'> {
  title?: string
  /** Mono text on the right of the header, e.g. "2 sections". */
  meta?: string
  trigger?: Snippet<[CollapsibleTriggerProps]>
  /** `card` draws the bordered box; `plain` only the row. */
  variant?: 'card' | 'plain'
  children?: Snippet
}
