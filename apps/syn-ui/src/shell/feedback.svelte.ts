/**
 * Shared state for the feedback bubble (#1385). The bubble and the dialog are
 * mounted lazily by AppShell, only on a developer machine, so neither joins
 * the first load. The dialog stays mounted once opened: closing it for the
 * element picker or a screenshot keeps the draft.
 */

/**
 * The bubble shows only where the API turns `ui_feedback` on AND the app is
 * running on a developer machine: the Vite dev server, or a fixtures build
 * (`VITE_SYN_FIXTURES=1`, what e2e serves). A deployed production build never
 * shows it, whatever the flag says. See CONVENTIONS.md, "Feedback bubble".
 */
export const FEEDBACK_LOCAL_ONLY: boolean = import.meta.env.DEV || import.meta.env.VITE_SYN_FIXTURES === '1'

/** What the dialog asks for when it opens: a plain note, or straight into the element picker. */
export type FeedbackStart = 'note' | 'pick'

export const feedbackUi = $state({
  /** The API said `ui_feedback: true` (set by the bubble). */
  enabled: false,
  open: false,
  mounted: false,
  /** Bumped on each open request so the dialog can react to `start`. */
  request: 0,
  start: 'note' as FeedbackStart,
  /** The element picker or area selector owns the screen (bubble hidden). */
  picking: false,
  /** Bumped after each successful submit, so the bubble recounts. */
  sent: 0,
  /** Bumped by the Recent feedback shortcut; the bubble opens its list. */
  recentRequest: 0,
})

/** Open the bubble's Recent feedback list; false while the feature is off. */
export function showFeedbackRecent(): boolean {
  if (!FEEDBACK_LOCAL_ONLY || !feedbackUi.enabled) return false
  feedbackUi.recentRequest += 1
  return true
}

/** Open the dialog; false while the feature is off, so a shortcut keeps its default. */
export function openFeedback(start: FeedbackStart = 'note'): boolean {
  if (!FEEDBACK_LOCAL_ONLY || !feedbackUi.enabled) return false
  feedbackUi.mounted = true
  feedbackUi.start = start
  feedbackUi.request += 1
  if (start === 'note') feedbackUi.open = true
  return true
}
