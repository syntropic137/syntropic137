import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'

/**
 * Callout (CompDisplay; no upstream contract yet). Amber says something is
 * uncertain, coral says something failed, the note is plain information.
 *
 * Static by default. For an error that appears after an action, pass
 * `role="alert"`; for a status update, `role="status"`.
 */
export type CalloutTone = 'warning' | 'danger' | 'note'

export interface CalloutProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children' | 'title'> {
  tone?: CalloutTone
  /** Bold lead-in: "Coverage can't be proven." */
  title?: string
  /** Replaces the default glyph. */
  icon?: Snippet
  /** A button or link after the text, e.g. "Retry". */
  action?: Snippet
  children?: Snippet
}
