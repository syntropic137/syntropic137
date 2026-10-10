import type { HarnessLanesProps as HarnessLanesData } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface HarnessLanesProps extends HarnessLanesData, Omit<HTMLAttributes<HTMLDivElement>, 'children'> {}
