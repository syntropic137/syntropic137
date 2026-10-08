import type { Snippet } from 'svelte'
import type { DialogRootContract } from '@syn137/skyline-core/contracts'
import type { TriggerProps } from '../_internal/trigger'

/**
 * Dialog (DialogRootContract). CompNav "dialog · transcript": a header with
 * the title, actions such as Copy all, and a close button; the page behind
 * dims to 60%.
 *
 * Built on the native <dialog> with showModal(), so focus is trapped, the
 * page is inert and Escape closes it. Focus returns to the trigger. On a
 * phone it rises from the bottom as a sheet.
 *
 * Open it with `bind:open`, or give it a `trigger` snippet.
 */
export type DialogSize = 'sm' | 'md' | 'lg' | 'full'

export interface DialogProps extends DialogRootContract {
  title?: string
  /** Mono suffix after the title ("2fd5ec12"). */
  titleId?: string
  description?: string
  size?: DialogSize
  /** Header controls before the close button. */
  actions?: Snippet
  footer?: Snippet
  trigger?: Snippet<[TriggerProps]>
  children?: Snippet<[{ close: () => void }]>
  /** Clicking the dimmed page closes the dialog. */
  closeOnBackdrop?: boolean
  showClose?: boolean
  /** `alertdialog` for confirmations (Alert Dialog sets it). */
  role?: 'dialog' | 'alertdialog'
  /** Element to focus on open; default is the first focusable control. */
  initialFocus?: () => HTMLElement | null | undefined
  /** Drop the body padding (the Command palette fills the dialog). */
  bare?: boolean
}
