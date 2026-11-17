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

  // Real values from GET /executions/exec-105b88d56234 (beta.7): the rows
  // account for the total exactly, but float subtraction leaves ~1e-17.
  it('shows no unattributed row when the rows account for the total exactly', () => {
    render(
      <ModelBreakdown
        costByModel={{ 'claude-opus-5-5': '0.30566780000000005', 'gpt-6-sol': '0.1324232' }}
        totalCost="0.43809100000000005"
        unpricedObservationCount={0}
      />,
    )
    expect(screen.getByText('claude-opus-5-5')).toBeTruthy()
    expect(screen.getByText('gpt-6-sol')).toBeTruthy()
    expect(screen.queryByText('not yet attributed')).toBeNull()
    expect(screen.queryByText('$0.000000')).toBeNull()
  })

  it('still shows a real mid-run remainder as not yet attributed (#1048)', () => {
    // Phase 2 is running: its per-model map is empty, the total already counts it.
    render(
      <ModelBreakdown
        costByModel={{ 'claude-opus-5-5': '0.30566780000000005' }}
        totalCost="0.43809100000000005"
        unpricedObservationCount={0}
      />,
    )
    expect(screen.getByText('not yet attributed')).toBeTruthy()
    expect(screen.getByText('$0.1324')).toBeTruthy()
  })

  it('lists a model that ran unpriced with the backend label, never as $0 (#1743)', () => {
    render(
      <ModelBreakdown
        costByModel={{ 'gpt-5.6-sol': '0.19' }}
        totalCost={0.19}
        unpricedObservationCount={1}
        unpricedModels={['acme-reasoner-7b']}
        unpricedLabel="unpriced"
      />,
    )
    const row = screen.getByText('acme-reasoner-7b').parentElement
    expect(row?.textContent).toContain('unpriced')
    expect(row?.textContent).not.toContain('$')
  })

  it('renders when the only models it has are unpriced ones (#1743)', () => {
    render(
      <ModelBreakdown
        costByModel={{}}
        totalCost={0}
        unpricedObservationCount={1}
        unpricedModels={['acme-reasoner-7b']}
        unpricedLabel="unpriced"
      />,
    )
    expect(screen.getByText('acme-reasoner-7b')).toBeTruthy()
  })
})
