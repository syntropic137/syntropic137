// Exhaustive lookups from each prop union this component renders to the
// data-* value its CSS styles. Keyed by the Props type, so a member added
// upstream (or locally) is a missing-key compile error here, never an
// unstyled value at runtime. Equality with the contract: src/contract-unions.ts.
import type { ToggleGroupProps } from './types'

export const TOGGLE_GROUP_SIZE = { sm: 'sm', md: 'md', lg: 'lg' } as const satisfies Record<NonNullable<ToggleGroupProps['size']>, string>

export const TOGGLE_GROUP_ORIENTATION = {
  horizontal: 'horizontal',
  vertical: 'vertical',
} as const satisfies Record<NonNullable<ToggleGroupProps['orientation']>, string>
