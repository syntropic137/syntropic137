import type { HTMLAttributes } from 'svelte/elements'
import type { ContractSize, ToggleGroupItemContract, ToggleGroupMultipleContract } from '@syn137/skyline-core/contracts'

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
 * The value is always a string array. Upstream ToggleGroupContract is a
 * union whose `single` arm takes a plain string; Skyline keeps the array for
 * both types, so it extends the `multiple` arm with `type` widened.
 */
export interface ToggleGroupProps extends Omit<ToggleGroupMultipleContract, 'type'>, Omit<HTMLAttributes<HTMLDivElement>, keyof ToggleGroupMultipleContract | 'children'> {
  type: 'single' | 'multiple'
  /** Skyline: upstream has no size. */
  size?: ContractSize
  items: ToggleGroupItem[]
  variant?: 'segmented' | 'chips'
  /** Mono labels (16w / Year). */
  mono?: boolean
  /** A single group may end with nothing pressed. */
  allowEmpty?: boolean
}
