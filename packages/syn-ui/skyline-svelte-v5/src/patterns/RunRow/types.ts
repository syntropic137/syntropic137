import type { RunRowProps as RunRowData } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface RunRowProps extends RunRowData, Omit<HTMLAttributes<HTMLElement>, 'children'> {}
