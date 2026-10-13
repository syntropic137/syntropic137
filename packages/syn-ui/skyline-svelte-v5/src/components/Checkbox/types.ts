import type { Snippet } from 'svelte'
import type { HTMLInputAttributes } from 'svelte/elements'
import type { CheckboxRootContract } from '@syn137/skyline-core/contracts'

/**
 * Checkbox (CheckboxRootContract): row selection and select-all. A native
 * checkbox under the drawn box, so forms and assistive tech get the real
 * thing. `checked="indeterminate"` draws the dash ("some rows"); use
 * `selectAllState()` from `@syn137/skyline-core/state` to compute it.
 * Without children, pass `aria-label`.
 */
export interface CheckboxProps extends CheckboxRootContract, Omit<HTMLInputAttributes, keyof CheckboxRootContract | 'children' | 'type'> {
  children?: Snippet
}
