// Exhaustive lookups from each prop union this component renders to the
// data-* value its CSS styles. Keyed by the Props type, so a member added
// upstream (or locally) is a missing-key compile error here, never an
// unstyled value at runtime. Equality with the contract: src/contract-unions.ts.
import type { ProgressProps } from './types'

export const PROGRESS_TONE = {
  neutral: 'neutral',
  accent: 'accent',
  danger: 'danger',
  warning: 'warning',
  success: 'success',
} as const satisfies Record<NonNullable<ProgressProps['tone']>, string>
