import type { Snippet } from 'svelte'
import type { HTMLButtonAttributes } from 'svelte/elements'
import type { SwitchRootContract } from '@syn137/skyline-core/contracts'

/**
 * Switch (CompActions "Switch and Checkbox"): a live setting such as a
 * trigger being active or paused. `bind:checked` or `checked` +
 * `onCheckedChange`. With `name` it also submits a hidden "on" field.
 * Children render as a clickable label after the track.
 */
export interface SwitchProps extends SwitchRootContract, Omit<HTMLButtonAttributes, keyof SwitchRootContract | 'children' | 'type' | 'value'> {
  value?: string
  children?: Snippet
}
