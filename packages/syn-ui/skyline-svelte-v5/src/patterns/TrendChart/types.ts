import type { TrendChartProps as TrendChartContract } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface TrendChartProps extends TrendChartContract, Omit<HTMLAttributes<HTMLDivElement>, 'children'> {}
