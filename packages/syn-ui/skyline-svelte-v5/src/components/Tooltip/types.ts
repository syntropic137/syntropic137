import type { Snippet } from 'svelte'
import type { TooltipRootContract } from '@syn137/skyline-core/contracts'
import type { TriggerProps } from '../_internal/trigger'

/**
 * Tooltip (TooltipRootContract). CompNav "tooltip": a raised note such as a
 * full ID and "Click to copy the full ID". Opens on hover after
 * `delayDuration`, at once on keyboard focus, closes on Escape.
 *
 * A tooltip only repeats or adds to what is on screen: nothing may be
 * reachable through a tooltip alone (touch has no hover). Spread the
 * trigger props onto your control:
 *
 *   <Tooltip content="exec-66e14f235942">
 *     {#snippet trigger(props)}<button {...props}>66e14f23</button>{/snippet}
 *   </Tooltip>
 */
export interface TooltipProps extends TooltipRootContract {
  /** Main line (mono when `mono`). */
  content?: string
  /** Second, muted line. */
  hint?: string
  mono?: boolean
  align?: 'start' | 'center' | 'end'
  trigger: Snippet<[TriggerProps]>
  /** Rich content instead of `content` / `hint`. */
  children?: Snippet
}
