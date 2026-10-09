/**
 * A long repository name on execution detail wraps inside its card
 * (feedback fc9f69a0, 5f2359cd, both at 411x780).
 *
 * `RepositoryRef.parse` accepts a name with no break opportunity at all, and
 * the Repositories card rendered it in an anchor that could neither wrap nor
 * shrink: verification measured the page 483px wide at 411px and 390px.
 *
 * jsdom does no layout, so this pins the rule that prevents it: the anchor
 * breaks anywhere, and the full URL stays reachable.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ExecutionDetailResponse } from '../../../types'
import { withPlanOfPhases } from '../../../test/phasePlanFixtures'

const useExecutionData = vi.fn()

vi.mock('../../../hooks', () => ({
  useExecutionData: (executionId: string | undefined) => useExecutionData(executionId),
}))

const { ExecutionDetail } = await import('../ExecutionDetail')

const LONG_NAME = 'r'.repeat(90)
const LONG_REPO = `syntropic137/${LONG_NAME}`

function withRepos(repos: string[]): ExecutionDetailResponse {
  return {
    workflow_execution_id: 'exec-long-repo',
    workflow_id: 'wf-1',
    workflow_name: 'implement',
    status: 'completed',
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    phases: [],
    total_phases: 0,
    completed_phases: 0,
    phase_progress: {
      completed: 0,
      skipped: 0,
      possible: 0,
      remaining_possible: 0,
      percent: 0,
      display: '0 of 0',
    },
    total_input_tokens: 0,
    total_output_tokens: 0,
    total_cache_creation_tokens: 0,
    total_cache_read_tokens: 0,
    total_tokens: 0,
    total_cost_usd: 0,
    unpriced_observation_count: 0,
    artifact_ids: [],
    error_message: null,
    repos,
    total_duration_seconds: 0,
  } as unknown as ExecutionDetailResponse
}

describe('execution detail at a phone width', () => {
  it('breaks a repository name with no break opportunity inside its card', () => {
    useExecutionData.mockReturnValue({
      execution: withPlanOfPhases(withRepos([LONG_REPO, 'syntropic137/event-sourcing-platform'])),
      artifactDetails: {},
      loading: false,
      error: null,
      isConnected: true,
      now: Date.now(),
      refreshExecution: vi.fn(),
    })
    render(
      <MemoryRouter initialEntries={['/executions/exec-long-repo']}>
        <ExecutionDetail />
      </MemoryRouter>,
    )
    const link = screen.getByRole('link', { name: LONG_NAME })
    expect(link).toHaveClass('break-all')
    expect(link).toHaveAttribute('title', LONG_REPO)
  })
})
