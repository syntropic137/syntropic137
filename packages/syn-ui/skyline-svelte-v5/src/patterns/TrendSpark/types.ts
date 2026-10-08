import type { TrendSparkProps as TrendSparkContract } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface TrendSparkProps extends TrendSparkContract, Omit<HTMLAttributes<HTMLSpanElement>, 'children'> {}
