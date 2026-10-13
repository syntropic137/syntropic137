// Exhaustive lookups from each prop union this component renders to the
// data-* value its CSS styles. Keyed by the Props type, so a member added
// upstream (or locally) is a missing-key compile error here, never an
// unstyled value at runtime. Equality with the contract: src/contract-unions.ts.
import type { TabsProps } from './types'

export const TABS_ORIENTATION = { horizontal: 'horizontal', vertical: 'vertical' } as const satisfies Record<NonNullable<TabsProps['orientation']>, string>
