import type { PageHeaderProps as PageHeaderData } from '@syn137/skyline-core/patterns'
import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'

export interface PageHeaderProps extends PageHeaderData, Omit<HTMLAttributes<HTMLElement>, 'title' | 'children'> {
  /** Buttons above the figures (desktop) or under them (phone). */
  actions?: Snippet
  /** Extra content under the title block: tags, Lineage Trail, Agent Prompt Button. */
  children?: Snippet
  /** Copy control beside the title label, e.g. "Copy task". */
  titleAction?: Snippet
  /** Heading level of the title (default 1). */
  level?: 1 | 2
}
