/**
 * Shared open state for the feedback modal (#1385). The button lives in two
 * navs (TopNav, PhoneTop) but the dialog is mounted once, in AppShell, and
 * only after the first click, so its chunk never joins the first load.
 */

/**
 * The button shows only where the API turns `ui_feedback` on AND the app is
 * running on a developer machine: the Vite dev server, or a fixtures build
 * (`VITE_SYN_FIXTURES=1`, what e2e serves). A deployed production build never
 * shows it, whatever the flag says. See CONVENTIONS.md, "Feedback modal".
 */
export const FEEDBACK_LOCAL_ONLY: boolean = import.meta.env.DEV || import.meta.env.VITE_SYN_FIXTURES === '1'

export const feedbackUi = $state({ open: false, mounted: false })

export function openFeedback(): void {
  feedbackUi.mounted = true
  feedbackUi.open = true
}
