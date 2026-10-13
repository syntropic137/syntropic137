// Exhaustive lookups from each prop union this component renders to the
// data-* value its CSS styles. Keyed by the Props type, so a member added
// upstream (or locally) is a missing-key compile error here, never an
// unstyled value at runtime. Equality with the contract: src/contract-unions.ts.
import type { ScrollAreaProps } from './types'

export const SCROLL_AREA_ORIENTATION = {
  horizontal: 'horizontal',
  vertical: 'vertical',
  both: 'both',
} as const satisfies Record<NonNullable<ScrollAreaProps['orientation']>, string>
