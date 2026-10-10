// Exhaustive lookups from each prop union this component renders to the
// data-* value its CSS styles. Keyed by the Props type, so a member added
// upstream (or locally) is a missing-key compile error here, never an
// unstyled value at runtime. Equality with the contract: src/contract-unions.ts.
import type { BadgeProps } from './types'

export const BADGE_VARIANT = { solid: 'solid', outline: 'outline', soft: 'soft' } as const satisfies Record<NonNullable<BadgeProps['variant']>, string>

export const BADGE_TONE = {
  neutral: 'neutral',
  accent: 'accent',
  danger: 'danger',
  warning: 'warning',
  success: 'success',
} as const satisfies Record<NonNullable<BadgeProps['tone']>, string>

export const BADGE_SIZE = { sm: 'sm', md: 'md' } as const satisfies Record<NonNullable<BadgeProps['size']>, string>
