import type { Snippet } from 'svelte'
import type { HTMLButtonAttributes } from 'svelte/elements'
import type { ButtonContract } from '@syn137/skyline-core/contracts'

/**
 * Button (CompActions board).
 *
 * | Canvas name | Props                                 |
 * |-------------|---------------------------------------|
 * | primary     | `variant="solid"` (tone defaults to accent) |
 * | secondary   | `variant="outline"` (the default)     |
 * | ghost       | `variant="ghost"`                     |
 * | danger      | `variant="outline" tone="danger"`     |
 * | icon only   | `icon` snippet, no children, `aria-label` |
 */
export interface ButtonProps extends ButtonContract, Omit<HTMLButtonAttributes, keyof ButtonContract | 'children'> {
  /** Visible label. */
  children?: Snippet
  /** Leading icon (15px). With no children the button is square. */
  icon?: Snippet
  /** Trailing icon, such as a chevron. */
  iconEnd?: Snippet
  /** Full width of its container (the phone's primary action). */
  block?: boolean
}
