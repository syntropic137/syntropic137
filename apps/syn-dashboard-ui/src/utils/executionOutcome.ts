import type { FailureClassification, ReportedFailureReason } from '../types'

/**
 * The one decision behind every failure-coloured surface in the dashboard
 * (#1367).
 *
 * THE DEFECT THIS EXISTS TO STOP. #1357 taught `StatusBadge` that a
 * `correct_refusal` is not the platform breaking, and taught nothing else. So
 * one run wore an amber "refused" badge inside a red "Execution Failed" card,
 * above a red progress bar, beside a red failed phase - and on Workflow Runs
 * it was plain red, because that page never passed the classification at all.
 * An operator scanning for outages saw five failures, four of them red, and
 * had no way to tell which of the reds was real.
 *
 * Fixing that per surface would leave five places that each have to remember
 * a rule, which is the same defect with a longer fuse. The rule is decided
 * here instead, and the answer is a PALETTE KEY: every caller already looks
 * its colours up by status, so substituting the key leaves each component
 * owning its own colours and owning none of the decision.
 */

/**
 * The key a correct refusal is drawn under.
 *
 * Exported so the palettes below use it as a computed key rather than
 * spelling it: a typo in one of five string literals would fail open, back to
 * the red this exists to remove, and would look exactly like working code.
 */
export const REFUSED = 'refused'

/**
 * The key a run that could not be done as asked is drawn under (#1372).
 *
 * Its own key rather than `REFUSED`'s, because it is its own fact and the key
 * is also the label: a phase judging work not deliverable and a phase finding
 * the request impossible take opposite actions from the operator, and a badge
 * that prints the same word for both hides the distinction #1372 added the
 * classification to make. Underscored because the label is rendered with the
 * underscore replaced by a space.
 */
export const TASK_FAILED = 'task_failed'

/**
 * Which classifications are drawn as something other than a plain failure.
 *
 * A table rather than a chain of comparisons so that adding a member to
 * `FailureClassification` is a line here and not an edit inside a condition -
 * the shape #1372 arrived at when `task` had to reach five surfaces that each
 * only knew about `correct_refusal`. What is NOT listed is as deliberate:
 * `platform` is the machinery breaking, `unclassified` is a run that ended
 * before anything recorded the difference, and both stay plain red.
 */
const TONE_FOR_CLASSIFICATION: Partial<Record<FailureClassification, string>> = {
  correct_refusal: REFUSED,
  task: TASK_FAILED,
}

/**
 * How to draw this outcome: the status, unless the status undersells it.
 *
 * The substitutions are claims about the SYSTEM rather than about the run.
 * The phase reported `success=false` and the platform recorded that
 * faithfully - so whether the work was judged not deliverable or the request
 * could not be done at all, nothing here is broken and nothing is red. Red is
 * for the machinery failing, which is the only thing an operator can fix by
 * looking at the platform.
 *
 * Every other failure is left exactly as it was: `unclassified` - a run
 * recorded before the field existed - has always been a plain failure and
 * must not be promoted into anything gentler by a UI that cannot know.
 *
 * `failureClassification` is optional because most callers - sessions,
 * phases, trigger firings - have no such thing to report, and a caller with
 * nothing to say must get back exactly the status it passed in.
 */
export function outcomeTone(
  status: string,
  failureClassification?: FailureClassification,
): string {
  if (status !== 'failed' || failureClassification === undefined) return status
  return TONE_FOR_CLASSIFICATION[failureClassification] ?? status
}

/**
 * True when this outcome is the platform failing - the only kind red is for.
 *
 * For the surfaces that are not a palette lookup: a heading that says
 * "Execution Failed", an icon that means something went wrong. Derived from
 * `outcomeTone` rather than re-deriving the rule, so the card and the bar
 * above it cannot ever disagree about the same run - and so a classification
 * added to the table above reaches these surfaces without being named twice.
 */
export function isPlatformFailure(
  status: string,
  failureClassification?: FailureClassification,
): boolean {
  return outcomeTone(status, failureClassification) === 'failed'
}

/**
 * What the agent SAID caused the failure, phrased so it reads as a quotation.
 *
 * THE DISTINCTION THIS PROTECTS (#1392). `failureClassification` above is a
 * measurement: it decides colour, it decides the heading, and every failure
 * number the platform is judged by is computed from it. This is the other
 * kind of fact entirely - a word the AGENT chose, corroborated by nothing but
 * the process having exited cleanly, which is evidence about the harness and
 * not about whether the task was possible. Drawn as the platform's own
 * finding it would let a run that gave up move itself out of the failure
 * count by typing one word, which is the defect #1392 was opened on.
 *
 * So it renders as attribution and never as a verdict - "the agent reported
 * …" - and it is deliberately NOT wired into `outcomeTone`: nothing an agent
 * writes may change a colour, because the colour is the measurement.
 *
 * The gloss is here rather than in the components for the reason
 * `TONE_FOR_CLASSIFICATION` is: a word added to the server's enum should be
 * one line in one table, not a string spelled the same way on three surfaces.
 * A member this build has never heard of falls through to the bare word,
 * which is still the truthful thing to show - the agent did write it.
 */
const REPORTED_REASON_MEANS: Partial<Record<ReportedFailureReason, string>> = {
  task: 'the request was wrong, impossible, or too big for one phase',
  platform: 'the machinery broke under it',
  refused: 'it could have done the work and judged it should not',
  unknown: 'it could not tell which of those it was',
}

/**
 * The sentence to show beside a failure, or `null` when the phase named nothing.
 *
 * `null` for a phase that named no cause - no key at all, which is every
 * report written before the field existed - because an absent report must
 * read as silence rather than as a reported "nothing".
 */
export function reportedFailureNote(
  reportedFailureReason?: ReportedFailureReason | null,
): string | null {
  if (!reportedFailureReason) return null
  const means = REPORTED_REASON_MEANS[reportedFailureReason]
  return means
    ? `The agent reported: ${reportedFailureReason} — ${means}.`
    : `The agent reported: ${reportedFailureReason}.`
}
