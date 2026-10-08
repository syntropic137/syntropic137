import type { HTMLAttributes } from 'svelte/elements'
import type { ToggleGroupContract, ToggleGroupItemContract } from '@syn137/skyline-core/contracts'

export interface ToggleGroupItem extends ToggleGroupItemContract {
  label: string
  /** Mono count after the label ("Completed 50"). */
  count?: number | string
}

/**
 * Toggle Group (CompActions "Toggle and Toggle Group").
 *
 * - `variant="segmented"`: Rendered / Raw, 16w / Year (`mono`).
 * - `variant="chips"`: status filter chips with counts. One row that scrolls
 *   sideways on a phone; wraps from 48rem.
 *
 * `type="single"` is a radio group: arrows move the choice. By default a
 * single group always keeps one item (`allowEmpty` false). `type="multiple"`
 * is a set of pressed buttons: arrows move focus, Space/Enter toggles.
 * The value is always a string array (upstream contract).
 */
export interface ToggleGroupProps extends ToggleGroupContract, Omit<HTMLAttributes<HTMLDivElement>, keyof ToggleGroupContract | 'children'> {
  items: ToggleGroupItem[]
  variant?: 'segmented' | 'chips'
  /** Mono labels (16w / Year). */
  mono?: boolean
  /** A single group may end with nothing pressed. */
  allowEmpty?: boolean
}
