import type { StatusBadgeShape } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface StatusBadgeProps extends Omit<HTMLAttributes<HTMLSpanElement>, 'children'> {
  /** Raw API status ("completed", "in_progress", "failed"...). */
  status: string | null | undefined
  /**
   * `pill`: glyph and label (page headers, lists).
   * `square`: the 32px glyph tile that starts a Run Row; the label is visually hidden.
   * `glyph`: the bare coloured glyph (attention chips).
   */
  shape?: StatusBadgeShape
  /** Overrides the label from statusSemantics(). */
  label?: string
}
