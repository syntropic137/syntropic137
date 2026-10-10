import type { HTMLButtonAttributes } from 'svelte/elements'

/**
 * Copy Button (CompActions "Copy Button"; pattern over Button). Copies a part
 * (an input, an output) or the whole list, then shows a check for a moment.
 *
 * - Icon only: no `label`; its accessible name is "Copy" (or `aria-label`).
 * - Section: `label="Copy all"` flips to "Copied all".
 *
 * Works on plain-HTTP self-hosted deployments too: without the async
 * Clipboard API it falls back to a hidden textarea and execCommand.
 */
export interface CopyButtonProps extends Omit<HTMLButtonAttributes, 'children' | 'type' | 'value'> {
  /** The text to copy. */
  text?: string
  /** Computes the text at click time (wins over `text`). */
  getText?: () => string | Promise<string>
  label?: string
  /** Shown after copying. Default: the label with "Copy" turned into "Copied". */
  copiedLabel?: string
  /** `sm` 32px (default), `xs` 30px for the corner of an output block. */
  size?: 'xs' | 'sm'
  onCopy?: (text: string) => void
  onError?: (error: unknown) => void
}
