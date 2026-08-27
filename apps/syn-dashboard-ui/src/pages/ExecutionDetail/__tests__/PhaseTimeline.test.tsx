/**
 * The Phase Pipeline header must not report unpriced work as $0.0000 (#890).
 *
 * The per-phase cards were fixed first; the header roll-up is a SECOND consumer
 * of the same coverage data and kept summing cost_usd alone. These cases pin
 * the aggregate specifically, because a suite that only checks the cards stays
 * green while the total above them lies.
 */

import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { PhaseTimeline } from '../PhaseTimeline'
import type { ExecutionDetailResponse } from '../../../types'

type Phase = ExecutionDetailResponse['phases'][number]

function phase(overrides: Partial<Phase> & { workflow_phase_id: string }): Phase {
  return {
    name: 'Phase',
    status: 'completed',
    session_id: null,
    agent_session_id: null,
    artifact_id: null,
    input_tokens: 100,
    output_tokens: 200,
    cache_creation_tokens: 0,
    cache_read_tokens: 0,
    duration_seconds: 1,
    cost_usd: 0,
    unpriced_observation_count: 0,
    started_at: null,
    completed_at: null,
    model: null,
    cost_by_model: {},
    ...overrides,
  } as Phase
}

function renderTimeline(phases: Phase[]) {
  return render(
    <MemoryRouter>
      <PhaseTimeline phases={phases} now={Date.now()} />
    </MemoryRouter>,
  )
}

/** The header total lives in the metrics strip above the phase cards. */
function headerCost(): string {
  const strip = document.querySelector('.flex.items-center.gap-4')
  return strip?.textContent ?? ''
}

describe('PhaseTimeline header roll-up', () => {
  it('renders a dollar figure when every phase is priced', () => {
    renderTimeline([
      phase({ workflow_phase_id: 'plan', cost_usd: 1.5 }),
      phase({ workflow_phase_id: 'build', cost_usd: 2.5 }),
    ])
    expect(headerCost()).toContain('$4.00')
    expect(headerCost()).not.toContain('unpriced')
  })

  it('says unpriced, not $0.0000, when no phase could be priced', () => {
    renderTimeline([
      phase({ workflow_phase_id: 'plan', cost_usd: 0, unpriced_observation_count: 4 }),
      phase({ workflow_phase_id: 'build', cost_usd: 0, unpriced_observation_count: 7 }),
    ])
    expect(headerCost()).toContain('unpriced')
    expect(headerCost()).not.toContain('$0.0000')
  })

  it('marks a mixed total as a lower bound rather than a complete figure', () => {
    renderTimeline([
      phase({ workflow_phase_id: 'plan', cost_usd: 3 }),
      phase({ workflow_phase_id: 'build', cost_usd: 0, unpriced_observation_count: 9 }),
    ])
    const text = headerCost()
    expect(text).toContain('(partial)')
    expect(text).toContain('$3.00')
  })

  it('treats a genuinely free priced execution as $0, not unpriced', () => {
    renderTimeline([phase({ workflow_phase_id: 'plan', cost_usd: 0 })])
    expect(headerCost()).not.toContain('unpriced')
  })
})
