import type { Snippet } from 'svelte'
import type { HTMLButtonAttributes } from 'svelte/elements'
import type { ContractSize, ToggleContract } from '@syn137/skyline-core/contracts'

/**
 * Toggle (CompActions board): a lone pressed chip such as "Expand all".
 * Use Switch for an on/off setting and Toggle Group for a set of chips.
 *
 * Controlled with `bind:pressed` (or `pressed` + `onPressedChange`),
 * uncontrolled with `defaultPressed`.
 */
export interface ToggleProps extends ToggleContract, Omit<HTMLButtonAttributes, keyof ToggleContract | 'children' | 'type'> {
  /** Skyline: upstream ToggleContract has no size. */
  size?: ContractSize
  children?: Snippet
  icon?: Snippet
}
