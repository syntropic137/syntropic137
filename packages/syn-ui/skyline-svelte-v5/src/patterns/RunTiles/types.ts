import type { RunTilesProps as RunTilesData } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface RunTilesProps extends RunTilesData, Omit<HTMLAttributes<HTMLDivElement>, 'children'> {}
