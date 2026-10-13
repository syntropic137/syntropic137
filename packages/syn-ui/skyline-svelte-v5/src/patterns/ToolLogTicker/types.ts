import type { ToolLogProps } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface ToolLogTickerProps extends ToolLogProps, Omit<HTMLAttributes<HTMLDivElement>, 'children'> {}
