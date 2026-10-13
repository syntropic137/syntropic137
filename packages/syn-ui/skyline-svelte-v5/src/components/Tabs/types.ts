import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'
import type { TabsRootContract, TabsTriggerContract } from '@syn137/skyline-core/contracts'

export interface TabsItem extends TabsTriggerContract {
  label: string
}

/**
 * Tabs (TabsRootContract): Rendered / Raw, Readable / JSON. Drawn like the
 * segmented toggle group, with tab semantics: one panel shows at a time.
 *
 *   <Tabs items={[{ value: 'rendered', label: 'Rendered' }, { value: 'raw', label: 'Raw' }]} bind:value>
 *     {#snippet children(active)}{active === 'raw' ? raw : rendered}{/snippet}
 *   </Tabs>
 */
export interface TabsProps extends TabsRootContract, Omit<HTMLAttributes<HTMLDivElement>, keyof TabsRootContract | 'children'> {
  items: TabsItem[]
  /** Skyline: `automatic` selects on focus; `manual` on activation. */
  activationMode?: 'automatic' | 'manual'
  /** Accessible name for the tab list. */
  label?: string
  mono?: boolean
  /** Extra controls on the tab row's far side (e.g. a Copy Button). */
  actions?: Snippet
  /** The active panel's content. */
  children?: Snippet<[string]>
}
