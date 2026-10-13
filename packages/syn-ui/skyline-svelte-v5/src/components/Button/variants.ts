// Exhaustive lookups from each prop union this component renders to the
// data-* value its CSS styles. Keyed by the Props type, so a member added
// upstream (or locally) is a missing-key compile error here, never an
// unstyled value at runtime. Equality with the contract: src/contract-unions.ts.
import type { ComponentTone } from '@syn137/skyline-core/contracts'
import type { ButtonProps, SkylineButtonVariant } from './types'

type Variant = NonNullable<ButtonProps['variant']>

export const BUTTON_SIZE = { sm: 'sm', md: 'md', lg: 'lg' } as const satisfies Record<NonNullable<ButtonProps['size']>, string>

/** Upstream names resolve onto Skyline's: primary = solid, secondary and danger = outline. */
export const BUTTON_VARIANT = {
  solid: 'solid',
  outline: 'outline',
  ghost: 'ghost',
  primary: 'solid',
  secondary: 'outline',
  danger: 'outline',
} as const satisfies Record<Variant, SkylineButtonVariant>

/** The tone a variant implies when no tone is given. */
export const BUTTON_VARIANT_TONE = {
  solid: 'accent',
  outline: 'neutral',
  ghost: 'neutral',
  primary: 'accent',
  secondary: 'neutral',
  danger: 'danger',
} as const satisfies Record<Variant, ComponentTone>

export const BUTTON_TONE = {
  neutral: 'neutral',
  accent: 'accent',
  danger: 'danger',
  warning: 'warning',
  success: 'success',
} as const satisfies Record<NonNullable<ButtonProps['tone']>, string>
