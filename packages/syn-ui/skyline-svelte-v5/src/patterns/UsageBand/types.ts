import type { UsageBandProps as UsageBandData } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export type UsageBandShape = 'extruded' | 'flat'
export type UsageBandLegend = 'full' | 'compact' | 'none'

export interface UsageBandProps extends UsageBandData, Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  /** Skyline: extruded strip (Usage Meter, default) or a flat bar (Landing pillar 03). */
  shape?: UsageBandShape
  /** Skyline: counts and shares per series (default), swatches and names only, or none. */
  legend?: UsageBandLegend
}
