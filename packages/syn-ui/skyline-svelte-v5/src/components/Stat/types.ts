import type { Snippet } from 'svelte'
import type { HTMLAttributes } from 'svelte/elements'

/**
 * Stat (CompDisplay board; no upstream contract yet): a caps mono label over
 * a tabular figure. Pass a preformatted string (use the skyline-core
 * formatters or the API's `*_display` value); null or undefined renders the
 * unknown dash in the muted colour.
 */
export type StatSize = 'sm' | 'md' | 'hero'

export interface StatProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  label: string
  value?: string | number | null
  /** `md` is 26px on a phone growing to 30px; `hero` is the 38px header figure. */
  size?: StatSize
  /** Line under the figure, e.g. "of 12 runs". */
  meta?: Snippet
  /** Replaces the figure (for a figure with an inline unit or badge). */
  children?: Snippet
}
