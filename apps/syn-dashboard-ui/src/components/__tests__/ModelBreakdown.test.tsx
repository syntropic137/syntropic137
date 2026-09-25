/**
 * Cost by Model shows observed ids verbatim and the unattributed bucket as
 * "unknown model" (ADR-067 D9), never the raw key and never a shortened id.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { UNATTRIBUTED_MODEL_KEY, UNATTRIBUTED_MODEL_LABEL } from '../../constants/models'
import { ModelBreakdown } from '../ModelBreakdown'

describe('ModelBreakdown', () => {
  it('renders the unattributed key as "unknown model"', () => {
    render(
      <ModelBreakdown
        costByModel={{ [UNATTRIBUTED_MODEL_KEY]: '0.2', 'claude-opus-5-5': '0.3' }}
        totalCost={0.5}
        unpricedObservationCount={0}
      />,
    )
    expect(screen.getByText(UNATTRIBUTED_MODEL_LABEL)).toBeTruthy()
    expect(screen.queryByText(UNATTRIBUTED_MODEL_KEY)).toBeNull()
  })

  it('renders the full observed id, not a shortened one', () => {
    render(
      <ModelBreakdown
        costByModel={{ 'claude-sonnet-5-20260101': '0.3' }}
        totalCost={0.3}
        unpricedObservationCount={0}
      />,
    )
    expect(screen.getByText('claude-sonnet-5-20260101')).toBeTruthy()
    expect(screen.queryByText('sonnet-5')).toBeNull()
  })
})
