/**
 * #1357: a correct refusal must not be drawn as a platform failure.
 *
 * Both are `status: "failed"`, and the dashboard is where an operator forms
 * the impression the issue is about - "the platform fails constantly" - from
 * a wall of red that includes every run the platform correctly refused.
 *
 * These assert the LABEL, not the class names. A colour is a decision that may
 * be re-themed; that the two say different words is the thing that must not
 * regress, and it is also the half that survives an operator who cannot
 * distinguish the two hues.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { StatusBadge } from '../StatusBadge'

describe('StatusBadge and the kind of failure', () => {
  it('draws a correct refusal apart from a platform failure', () => {
    const { unmount } = render(<StatusBadge status="failed" failureClassification="correct_refusal" />)
    const refused = screen.getByText('refused')
    unmount()

    render(<StatusBadge status="failed" failureClassification="platform" />)
    const failed = screen.getByText('failed')

    expect(refused.textContent).not.toBe(failed.textContent)
  })

  it('renders a platform failure exactly as it always did', () => {
    render(<StatusBadge status="failed" failureClassification="platform" />)

    expect(screen.getByText('failed')).toBeTruthy()
  })

  it('renders a failure recorded before #1357 as a plain failure', () => {
    // `unclassified` is every run in the store that predates the field. It has
    // always rendered as a failure and must keep doing so - the UI does not
    // get to guess what the record did not say.
    render(<StatusBadge status="failed" failureClassification="unclassified" />)

    expect(screen.getByText('failed')).toBeTruthy()
  })

  it('leaves a caller with no classification untouched', () => {
    // Sessions, phases and trigger firings pass nothing. The prop is optional
    // and its absence must not change a single badge they render.
    render(<StatusBadge status="failed" />)

    expect(screen.getByText('failed')).toBeTruthy()
  })

  it('never calls a non-failure a refusal', () => {
    // Nothing but `failed` can be refused, whatever a stale or wrong
    // classification says, because `status` is the fact about delivery.
    render(<StatusBadge status="completed" failureClassification="correct_refusal" />)

    expect(screen.getByText('completed')).toBeTruthy()
  })
})
