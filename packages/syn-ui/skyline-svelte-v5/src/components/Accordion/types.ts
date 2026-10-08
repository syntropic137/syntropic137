import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'
import type { AccordionContract } from '@syn137/skyline-core/contracts'

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
 */
export interface AccordionProps extends AccordionContract, Omit<HTMLAttributes<HTMLDivElement>, keyof AccordionContract | 'children'> {
  items: AccordionItem[]
  /** Heading level wrapping each header button. */
  level?: 2 | 3 | 4 | 5 | 6
  children?: Snippet<[AccordionItem]>
}
