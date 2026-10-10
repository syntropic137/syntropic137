// Exhaustive lookups from each prop union this component renders to the
// data-* value its CSS styles. Keyed by the Props type, so a member added
// upstream (or locally) is a missing-key compile error here, never an
// unstyled value at runtime. Equality with the contract: src/contract-unions.ts.
import type { MeterProps } from './types'

export const METER_TONE = {
  neutral: 'neutral',
  accent: 'accent',
  danger: 'danger',
  warning: 'warning',
  success: 'success',
} as const satisfies Record<NonNullable<MeterProps['tone']>, string>
