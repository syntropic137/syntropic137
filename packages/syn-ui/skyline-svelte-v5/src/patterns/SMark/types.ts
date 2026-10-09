import type { SMarkProps as SMarkData } from '@syn137/skyline-core/patterns'
import type { SVGAttributes } from 'svelte/elements'

export interface SMarkProps extends SMarkData, Omit<SVGAttributes<SVGSVGElement>, 'children'> {}
