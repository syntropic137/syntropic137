import type { PhaseBlockInput } from '@syn137/skyline-core/geometry'
import type { SVGAttributes } from 'svelte/elements'

export interface PhaseBlocksProps extends Omit<SVGAttributes<SVGSVGElement>, 'children'> {
  /** Phases in order. Map statuses with phaseTone(); give `meta` and `metaShort` for the line under each name. */
  phases: readonly PhaseBlockInput[]
  /** Accessible summary; defaults to each phase's name and meta. */
  label?: string
}
