/**
 * Shared state for the feedback bubble (#1385). The bubble and the dialog are
 * mounted lazily by AppShell, so neither joins the first load. The dialog stays mounted once opened: closing it for the
 * element picker or a screenshot keeps the draft.
 */

/**
 * The bubble shows wherever the API turns `ui_feedback` on (`GET /features`),
 * in every build. The server flag is the only switch: it is off by default for
 * open-source installs and on for the owner's VPS (2026-10-13, owner request:
 * leave feedback on the deployed site, not only from a dev build). The chunk is
 * still lazy, so it never joins the first load. See CONVENTIONS.md, "Feedback bubble".
 */

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
  if (!feedbackUi.enabled) return false
  feedbackUi.recentRequest += 1
  return true
}

/** Open the dialog; false while the feature is off, so a shortcut keeps its default. */
export function openFeedback(start: FeedbackStart = 'note'): boolean {
  if (!feedbackUi.enabled) return false
  feedbackUi.mounted = true
  feedbackUi.start = start
  feedbackUi.request += 1
  if (start === 'note') feedbackUi.open = true
  return true
}
