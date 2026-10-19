import type { Snippet } from 'svelte'
import type { HTMLButtonAttributes } from 'svelte/elements'
import type { ButtonContract, ButtonVariant, ContractTone } from '@syn137/skyline-core/contracts'

/** Skyline's own variant names. */
export type SkylineButtonVariant = 'solid' | 'outline' | 'ghost'

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
 *
 * Upstream's variant names (`primary`, `secondary`, `ghost`, `danger`) are
 * accepted too and map onto the rows above, so ButtonContract conforms.
 */
export interface ButtonProps extends Omit<ButtonContract, 'variant'>, Omit<HTMLButtonAttributes, keyof ButtonContract | 'children'> {
  variant?: SkylineButtonVariant | ButtonVariant
  /** Skyline: upstream ButtonContract has no tone. */
  tone?: ContractTone
  /** Skyline: renders an <a> when set. */
  href?: string
  /** Visible label. */
  children?: Snippet
  /** Leading icon (15px). With no children the button is square. */
  icon?: Snippet
  /** Trailing icon, such as a chevron. */
  iconEnd?: Snippet
  /** Full width of its container (the phone's primary action). */
  block?: boolean
}
