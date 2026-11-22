/**
 * The Runs card links to the full list with an arrow, not with the six
 * characters "→": a JSX attribute string does not process JS escapes.
 *
 * The Total Tokens card shows the cost the API rendered for `?workflow_id=`
 * and says when some of it could not be priced (#897).
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { ANY_UNPRICED_NOTE, COST_COVERAGE_CASES } from '../../../test/costCoverageFixtures'
import type { components } from '../../../generated/api-types'
import type { MetricsResponse, WorkflowResponse } from '../../../types'
import { WorkflowMetrics } from '../WorkflowMetrics'

const WORKFLOW: WorkflowResponse = {
  id: 'multi-agent-programmatic',
  name: 'Multi-agent (claude plans, codex implements)',
  description: null,
  workflow_type: 'research',
  classification: 'simple',
  phases: [],
  input_declarations: [],
  created_at: null,
  runs_count: 2,
  runs_link: '/api/workflows/multi-agent-programmatic/runs',
}

describe('WorkflowMetrics', () => {
  it('renders the Runs link subtitle with a real arrow', () => {
    const { container } = render(
      <MemoryRouter>
        <WorkflowMetrics
          workflow={WORKFLOW}
          metrics={null}
          artifactCount={4}
          executions={[]}
          workflowId="multi-agent-programmatic"
        />
      </MemoryRouter>,
    )
    expect(screen.getByText('View all →')).toBeTruthy()
    expect(container.textContent).not.toContain('\\u2192')
  })
})

describe.each(COST_COVERAGE_CASES)('WorkflowMetrics total cost, $name', (c) => {
  it('shows the API display and the coverage note only when something was unpriced', () => {
    // The /metrics body as the API sends it, checked against the generated
    // schema, then handed over as `getMetrics` does (no conversion).
    const wire = {
      total_workflows: 1,
      completed_workflows: 1,
      failed_workflows: 0,
      execution_status_counts: {
        not_started: 0,
        running: 0,
        completed: 1,
        failed: 0,
        cancelled: 0,
        interrupted: 0,
      },
      total_sessions: 1,
      total_input_tokens: 10,
      total_output_tokens: 20,
      total_cache_creation_tokens: 0,
      total_cache_read_tokens: 0,
      total_tokens: 30,
      total_cost_usd: c.total_cost_usd,
      total_cost_display: c.total_cost_display,
      unpriced_observation_count: c.unpriced_observation_count,
      total_artifacts: 0,
      total_artifact_bytes: 0,
      phases: [],
    } satisfies components['schemas']['MetricsResponse']
    const metrics = wire as unknown as MetricsResponse
    render(
      <MemoryRouter>
        <WorkflowMetrics
          workflow={WORKFLOW}
          metrics={metrics}
          artifactCount={0}
          executions={[]}
          workflowId="multi-agent-programmatic"
        />
      </MemoryRouter>,
    )

    expect(screen.getByText(c.shows)).toBeTruthy()
    if (c.note) expect(screen.getByText(c.note)).toBeTruthy()
    else expect(screen.queryByText(ANY_UNPRICED_NOTE)).toBeNull()
  })
})
