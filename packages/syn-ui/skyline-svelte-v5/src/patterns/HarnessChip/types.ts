import type { HarnessChipProps as HarnessChipData } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface HarnessChipProps extends HarnessChipData, Omit<HTMLAttributes<HTMLSpanElement>, 'children'> {}
