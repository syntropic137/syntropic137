import type { Snippet } from 'svelte'
import type { AlertDialogRootContract } from '@syn137/skyline-core/contracts'
import type { TriggerProps } from '../_internal/trigger'

/**
 * Alert Dialog (AlertDialogRootContract). CompNav "alert dialog": "Delete
 * this trigger?", one line on what happens, Cancel and the action.
 *
 * Focus starts on Cancel, the least destructive choice. The backdrop does not
 * dismiss it; Escape and Cancel do. When `onConfirm` returns a promise the
 * action shows as busy until it settles; a rejection keeps the dialog open
 * and shows the error message.
 */
export interface AlertDialogProps extends AlertDialogRootContract {
  title: string
  /** Plain-text description; use `children` for rich text. */
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  /** `danger` for destructive actions (the default), `accent` otherwise. */
  tone?: 'danger' | 'accent'
  onConfirm?: () => void | Promise<unknown>
  onCancel?: () => void
  trigger?: Snippet<[TriggerProps]>
  children?: Snippet
}
