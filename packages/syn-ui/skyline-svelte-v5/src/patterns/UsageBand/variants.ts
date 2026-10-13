import type { UsageBandProps } from './types'

export const USAGE_BAND_SHAPE = { extruded: 'extruded', flat: 'flat' } as const satisfies Record<NonNullable<UsageBandProps['shape']>, string>
export const USAGE_BAND_LEGEND = { full: 'full', compact: 'compact', none: 'none' } as const satisfies Record<NonNullable<UsageBandProps['legend']>, string>
