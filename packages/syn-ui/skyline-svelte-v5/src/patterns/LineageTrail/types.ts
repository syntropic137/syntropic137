import type { LineageStep } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface LineageTrailProps extends Omit<HTMLAttributes<HTMLElement>, 'children'> {
  /** Workflow to execution to phase to session; steps without `href` render as plain chips. */
  steps: readonly LineageStep[]
}
