import type { Snippet } from 'svelte'
import type { HTMLLabelAttributes } from 'svelte/elements'
import type { LabelContract } from '@syn137/skyline-core/contracts'

/**
 * Label (LabelContract). CompActions: the field name on the left and, on the
 * right, a mono hint that says what is required ("required · $ARGUMENTS").
 */
export interface LabelProps extends LabelContract, Omit<HTMLLabelAttributes, keyof LabelContract | 'children'> {
  /** Skyline: upstream LabelContract has no required flag. */
  required?: boolean
  /** Mono hint on the right. With `required` it follows "required · ". */
  hint?: string
  children?: Snippet
}
