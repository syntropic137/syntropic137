/**
 * The Runs card links to the full list with an arrow, not with the six
 * characters "→": a JSX attribute string does not process JS escapes.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { WorkflowResponse } from '../../../types'
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
