/**
 * The session's Total Cost card shows the API's `total_cost_display` verbatim
 * (#897): the backend's `format_cost` words the figure and its coverage, so the
 * session page cannot disagree with the CLI or the rest of the dashboard.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { COST_COVERAGE_CASES } from '../../../test/costCoverageFixtures'
import type { SessionResponse } from '../../../types'
import { SessionMetrics } from '../SessionMetrics'

function session(overrides: Partial<SessionResponse>): SessionResponse {
  return {
    id: 'sess-1',
    workflow_id: 'wf-1',
    workflow_name: null,
    execution_id: 'exec-1',
    phase_id: 'plan',
    phase_display: 'Plan',
    milestone_id: null,
    agent_provider: 'claude',
    agent_model: null,
    requested_model: null,
    agent_model_display: '—',
    status: 'completed',
    input_tokens: 0,
    output_tokens: 0,
    cache_creation_tokens: 0,
    cache_read_tokens: 0,
    total_tokens: 0,
    total_cost_usd: 0,
    total_cost_display: '$0.00',
    unpriced_observation_count: 0,
    cost_by_model: {},
    operations: [],
    started_at: null,
    completed_at: null,
    duration_seconds: 26.6,
    error_message: null,
    metadata: {},
    ...overrides,
  }
}

describe('session Total Cost card', () => {
  // The API words the cost (`format_cost`, #897). Only the partial case and
  // the sub-cent case below are worded differently by the client (U+2265,
  // four or six decimals); those are the ones that catch a regression.
  it.each(COST_COVERAGE_CASES)('shows the API cost text verbatim when $name', (c) => {
    const { container } = render(
      <SessionMetrics
        session={session({
          total_cost_usd: Number(c.total_cost_usd),
          total_cost_display: c.total_cost_display,
          unpriced_observation_count: c.unpriced_observation_count,
        })}
        now={0}
      />,
    )
    expect(screen.getByText(c.shows)).toBeTruthy()
    expect(container.textContent).not.toContain('$1.2500')
    expect(container.textContent).not.toContain('$0.0000')
  })

  it('shows a sub-cent cost as the API words it, not as six decimals', () => {
    // The client would render '$0.004000'; the API says '<$0.01' (format_cost).
    render(
      <SessionMetrics session={session({ total_cost_usd: 0.004, total_cost_display: '<$0.01' })} now={0} />,
    )
    expect(screen.getByText('<$0.01')).toBeTruthy()
  })
})
