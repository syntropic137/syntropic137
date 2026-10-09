import type { HTMLAttributes } from 'svelte/elements'

export interface KeycapsProps extends Omit<HTMLAttributes<HTMLSpanElement>, 'children'> {
  /** One label per key, in press order: `['⌃', '⇧', 'F']` or `['Ctrl', 'Shift', 'F']`. */
  keys: readonly string[]
  /** Accessible name for the whole combination; defaults to the labels joined with "+". */
  label?: string
}
