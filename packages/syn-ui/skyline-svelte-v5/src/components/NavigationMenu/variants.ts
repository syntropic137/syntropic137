// Exhaustive lookups from each prop union this component renders to the
// data-* value its CSS styles. Keyed by the Props type, so a member added
// upstream (or locally) is a missing-key compile error here, never an
// unstyled value at runtime. Equality with the contract: src/contract-unions.ts.
import type { NavigationMenuProps } from './types'

export const NAV_ORIENTATION = {
  horizontal: 'horizontal',
  vertical: 'vertical',
} as const satisfies Record<NonNullable<NavigationMenuProps['orientation']>, string>
