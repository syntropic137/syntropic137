/**
 * Trigger props for overlay components. A component hands these to its
 * `trigger` snippet; the caller spreads them onto its own control:
 *
 *   <Popover label="Filter">
 *     {#snippet trigger(props)}<Button {...props}>Filter</Button>{/snippet}
 *     ...
 *   </Popover>
 *
 * The object carries a Svelte attachment under a symbol key, which hands the
 * rendered element back to the overlay for positioning and focus return.
 * Spreading through a Skyline component works because components spread
 * `...rest` onto their host element.
 */
import { createAttachmentKey } from 'svelte/attachments'

export interface TriggerProps {
  id?: string
  'aria-expanded'?: boolean
  'aria-controls'?: string
  'aria-haspopup'?: 'dialog' | 'menu' | 'listbox' | 'true'
  'aria-describedby'?: string
  'data-state': 'open' | 'closed'
  onclick?: (e: MouseEvent) => void
  onkeydown?: (e: KeyboardEvent) => void
  onpointerenter?: (e: PointerEvent) => void
  onpointerleave?: (e: PointerEvent) => void
  onfocus?: (e: FocusEvent) => void
  onblur?: (e: FocusEvent) => void
  [key: symbol]: (node: HTMLElement) => void | (() => void)
}

export type RefAttachment = { [key: symbol]: (node: HTMLElement) => () => void }

/**
 * Create once per component instance, then spread into the trigger props.
 * Keeping the same key and function means the attachment runs once per
 * element, not on every state change.
 */
export function refAttachment(ref: (node: HTMLElement | null) => void): RefAttachment {
  return {
    [createAttachmentKey()]: (node: HTMLElement) => {
      ref(node)
      return () => ref(null)
    },
  }
}
