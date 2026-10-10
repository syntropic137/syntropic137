import type { VerdictCase, VerdictMatrix, Verifier } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface VerdictBoardProps extends Omit<HTMLAttributes<HTMLElement>, 'title' | 'children' | 'onselect'> {
  title?: string
  /** Suite chip beside the title: "verifier-seed-v1 · v2". */
  suite?: string
  description?: string
  cases: readonly VerdictCase[]
  verifiers: readonly Verifier[]
  /** Cells keyed with cellKey(caseId, verifierId). */
  cells: VerdictMatrix
  /** Selected cell key. Bindable; defaults to the first cell. */
  selected?: string | null
  onselect?: (caseId: string, verifierId: string) => void
}
