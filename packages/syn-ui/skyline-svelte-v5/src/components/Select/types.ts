import type { HTMLSelectAttributes } from 'svelte/elements'
import type { SelectRootContract } from '@syn137/skyline-core/contracts'

/**
 * Select (SelectRootContract): Sort, Status, Phase, Attempt. A styled native
 * <select>, so phones get their own picker and keyboard support is the
 * browser's. `label` draws the inline prefix from the canvas ("Sort  Most
 * run"); without it, pass `aria-label`.
 */
export interface SelectProps extends SelectRootContract, Omit<HTMLSelectAttributes, keyof SelectRootContract | 'children' | 'multiple'> {
  /** Inline prefix inside the field, also its accessible label. */
  label?: string
  invalid?: boolean
}
