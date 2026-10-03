/**
 * Which failures the dashboard is allowed to draw red (#1372).
 *
 * Red is a claim: THE MACHINERY BROKE, GO AND FIX IT. #1367 established that
 * and removed it from correct refusals across five surfaces. #1372 then added
 * `task` - a run the platform delivered intact, whose BRIEF could not be done
 * - and every one of those surfaces would have drawn it red again, because
 * each knew only the one classification it had been taught.
 *
 * These test the rule where it is decided rather than where it is drawn. The
 * surface tests beside them prove the rule reaches the pixels; this proves it
 * says the right thing, including for the values it must NOT move.
 */

import { describe, expect, it } from 'vitest'

import type { FailureClassification } from '../../types'
import { REFUSED, TASK_FAILED, isPlatformFailure, outcomeTone } from '../executionOutcome'

describe('outcomeTone', () => {
  it('draws a task failure under its own key', () => {
    expect(outcomeTone('failed', 'task')).toBe(TASK_FAILED)
  })

  it('does not draw a task failure as a refusal', () => {
    // The key is also the badge LABEL, so collapsing these prints "refused"
    // over a run nobody refused - and sends the operator to read and close
    // instead of to rewrite the brief.
    expect(outcomeTone('failed', 'task')).not.toBe(REFUSED)
    expect(outcomeTone('failed', 'correct_refusal')).toBe(REFUSED)
  })

  it('leaves a platform failure and an unclassified run plainly failed', () => {
    // The control. A table that renamed everything would pass the two above.
    expect(outcomeTone('failed', 'platform')).toBe('failed')
    expect(outcomeTone('failed', 'unclassified')).toBe('failed')
    expect(outcomeTone('failed')).toBe('failed')
  })

  it('never touches a status that did not fail', () => {
    // Sessions, phases and trigger firings pass no classification, and a run
    // still running carries whatever the last one left in the row.
    expect(outcomeTone('running', 'task')).toBe('running')
    expect(outcomeTone('completed', 'task')).toBe('completed')
    expect(outcomeTone('cancelled')).toBe('cancelled')
  })
})

describe('isPlatformFailure', () => {
  it('is false for a task failure', () => {
    // This one drives the heading on the detail page. True here prints
    // "Execution Failed" in red over a run where nothing failed but the
    // request, which is the #1367 defect arriving on the new member.
    expect(isPlatformFailure('failed', 'task')).toBe(false)
  })

  it('is still true for the thing red is for', () => {
    expect(isPlatformFailure('failed', 'platform')).toBe(true)
    expect(isPlatformFailure('failed', 'unclassified')).toBe(true)
  })

  it('agrees with outcomeTone on every classification', () => {
    // The two are read by different surfaces in the same card. Derived from
    // one rule so they cannot disagree; asserted so that staying derived is
    // not merely a comment.
    const all: FailureClassification[] = ['platform', 'task', 'correct_refusal', 'unclassified']

    for (const classification of all) {
      expect(isPlatformFailure('failed', classification)).toBe(
        outcomeTone('failed', classification) === 'failed',
      )
    }
  })
})
