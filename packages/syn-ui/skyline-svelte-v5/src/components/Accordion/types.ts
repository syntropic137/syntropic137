import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'
import type { AccordionMultipleContract } from '@syn137/skyline-core/contracts'

export interface AccordionItem {
  value: string
  title: string
  /** Mono text on the right of the header. */
  meta?: string
  disabled?: boolean
}

/**
 * Accordion (AccordionContract): trigger rules that open in place on a
 * phone. Headers are buttons inside headings; arrow keys, Home and End move
 * between headers. `type="single"` keeps one open (`collapsible` lets it
 * close again); `type="multiple"` any number. Content comes from the
 * `children` snippet, called with the item.
 *
 * Upstream AccordionContract is a union whose `single` arm takes a plain
 * string; Skyline keeps a string array for both types (like Toggle Group).
 */
export interface AccordionProps extends Omit<AccordionMultipleContract, 'type'>, Omit<HTMLAttributes<HTMLDivElement>, keyof AccordionMultipleContract | 'children'> {
  type: 'single' | 'multiple'
  /** Skyline: with `single`, whether the open item can be closed again. */
  collapsible?: boolean
  items: AccordionItem[]
  /** Heading level wrapping each header button. */
  level?: 2 | 3 | 4 | 5 | 6
  children?: Snippet<[AccordionItem]>
}
