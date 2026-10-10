import type { HTMLButtonAttributes } from 'svelte/elements'

export interface CopyButtonProps extends Omit<HTMLButtonAttributes, 'children' | 'onclick' | 'onerror'> {
  /** What to copy; a function is read at click time (e.g. "Copy all" of a filtered list). */
  text: string | (() => string)
  /** Accessible name, and the visible label for `variant="label"`: "Copy the Bash input". */
  label?: string
  /** Shown and announced after a copy: "Copied the output". */
  copiedLabel?: string
  /** `icon`: a 28px glyph button (44px on touch). `label`: a ghost text button ("Copy all"). */
  variant?: 'icon' | 'label'
  oncopied?: (text: string) => void
  onerror?: (error: unknown) => void
}
