import type { FailureClassification } from '../types'

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
 * How to draw this outcome: the status, unless the status undersells it.
 *
 * `failed` + `correct_refusal` is the one substitution, and it is a claim
 * about the SYSTEM rather than about the run - the phase reported
 * `success=false`, and the platform recorded that faithfully, so nothing here
 * is broken and nothing is red. Every other failure, including
 * `unclassified`, is left exactly as it was: a run recorded before the field
 * existed has always been a plain failure and must not be promoted into a
 * refusal by a UI that cannot know.
 *
 * `failureClassification` is optional because most callers - sessions,
 * phases, trigger firings - have no such thing to report, and a caller with
 * nothing to say must get back exactly the status it passed in.
 */
export function outcomeTone(
  status: string,
  failureClassification?: FailureClassification,
): string {
  if (status === 'failed' && failureClassification === 'correct_refusal') return REFUSED
  return status
}

/**
 * True when this outcome is the platform failing - the only kind red is for.
 *
 * For the surfaces that are not a palette lookup: a heading that says
 * "Execution Failed", an icon that means something went wrong. Derived from
 * `outcomeTone` rather than re-deriving the rule, so the card and the bar
 * above it cannot ever disagree about the same run.
 */
export function isPlatformFailure(
  status: string,
  failureClassification?: FailureClassification,
): boolean {
  return outcomeTone(status, failureClassification) === 'failed'
}
