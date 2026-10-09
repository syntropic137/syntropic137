import type { EvalExplorerProps as EvalExplorerData } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface EvalExplorerProps extends EvalExplorerData, Omit<HTMLAttributes<HTMLDivElement>, 'children' | 'onselect'> {
  /** Called with the verifier index when the reader picks a row (click, hover, arrow keys). */
  onselect?: (index: number) => void
}
