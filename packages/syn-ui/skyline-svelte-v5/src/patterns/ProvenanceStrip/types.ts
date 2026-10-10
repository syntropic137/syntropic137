import type { ProvenanceStripProps as ProvenanceData } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface ProvenanceStripProps extends ProvenanceData, Omit<HTMLAttributes<HTMLElement>, 'title' | 'children'> {
  /** Runs the action button (e.g. load the latest revision). */
  onaction?: () => void
  /** Disables the action while it runs. */
  busy?: boolean
}
