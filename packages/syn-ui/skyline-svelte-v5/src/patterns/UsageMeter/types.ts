import type { UsageMeterProps as UsageMeterData } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface UsageMeterProps extends UsageMeterData, Omit<HTMLAttributes<HTMLElement>, 'title' | 'children'> {}
