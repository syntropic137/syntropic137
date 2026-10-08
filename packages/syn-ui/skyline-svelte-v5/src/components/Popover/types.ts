import type { Snippet } from 'svelte'
import type { PopoverContentContract, PopoverRootContract } from '@syn137/skyline-core/contracts'
import type { TriggerProps } from '../_internal/trigger'

/**
 * Popover (PopoverRootContract). CompNav "popover · phone filter": a raised
 * panel anchored to its trigger, e.g. the status filter on a phone.
 *
 * Non-modal: Escape, a click outside, or tabbing out closes it. Focus moves
 * into the panel on open and back to the trigger on Escape. The content
 * snippet receives `close`.
 *
 *   <Popover label="Filter by status">
 *     {#snippet trigger(props)}<Button {...props}>Status</Button>{/snippet}
 *     {#snippet children({ close })}...{/snippet}
 *   </Popover>
 */
export interface PopoverProps extends PopoverRootContract, Pick<PopoverContentContract, 'side'> {
  /** Accessible name of the panel. */
  label: string
  /** Mono caps heading inside the panel ("STATUS"). */
  heading?: string
  align?: 'start' | 'center' | 'end'
  /** CSS width of the panel, default 15rem. */
  width?: string
  trigger: Snippet<[TriggerProps]>
  children?: Snippet<[{ close: () => void }]>
}
