/**
 * The execution page's Eval badge (Evals v2): an execution that is a run of an
 * eval links to it and shows its current verdict, read from the detail
 * response's `eval`; an execution in no eval shows nothing.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ExecutionDetailResponse, PhaseExecutionDetail } from '../../../types'
import { withPlanOfPhases } from '../../../test/phasePlanFixtures'

const useExecutionData = vi.fn()

vi.mock('../../../hooks', () => ({
  useExecutionData: (executionId: string | undefined) => useExecutionData(executionId),
}))

const { ExecutionDetail } = await import('../ExecutionDetail')

function phase(name: string, status: string): PhaseExecutionDetail {
  return {
    phase_id: name,
    name,
    status,
    session_id: null,
    agent_session_id: null,
    artifact_id: null,
    input_tokens: 0,
    output_tokens: 0,
    cache_creation_tokens: 0,
    cache_read_tokens: 0,
    duration_seconds: 0,
    cost_usd: 0,
    unpriced_observation_count: 0,
    started_at: new Date().toISOString(),
    completed_at: null,
    model: null,
    cost_by_model: {},
  } as unknown as PhaseExecutionDetail
}

/** The issue's run: three phases declared, implement done, verify died. */
function runOf(
  overrides: Partial<ExecutionDetailResponse> = {},
): ExecutionDetailResponse {
  return {
    workflow_execution_id: 'exec-0cd860b80128',
    workflow_id: 'wf-1147',
    workflow_name: 'implement-verify-report',
    status: 'failed',
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    phases: [phase('implement', 'completed'), phase('verify', 'failed')],
    total_phases: 3,
    completed_phases: 1,
    phase_progress: {
      completed: 1,
      skipped: 0,
      possible: 3,
      remaining_possible: 0,
      percent: 33,
      display: '1 of up to 3, failed',
    },
    total_input_tokens: 0,
    total_output_tokens: 0,
    total_cache_creation_tokens: 0,
    total_cache_read_tokens: 0,
    total_tokens: 0,
    total_cost_usd: 0,
    unpriced_observation_count: 0,
    artifact_ids: [],
    error_message: 'phase timed out',
    repos: [],
    total_duration_seconds: 0,
    ...overrides,
  } as unknown as ExecutionDetailResponse
}

function renderExecution(execution: ExecutionDetailResponse) {
  useExecutionData.mockReturnValue({
    execution: execution && withPlanOfPhases(execution),
    artifactDetails: {},
    loading: false,
    error: null,
    isConnected: true,
    now: Date.now(),
    refreshExecution: vi.fn(),
  })
  return render(
    <MemoryRouter initialEntries={['/executions/exec-0cd860b80128']}>
      <ExecutionDetail />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  useExecutionData.mockReset()
})

describe('ExecutionDetail eval badge', () => {
  it('links a run of an eval to the eval, with its verdict', () => {
    renderExecution(
      runOf({
        eval: {
          eval_id: 'eval-7f3a',
          eval_name: 'verifier-seed: case-1',
          association_kind: 'launched',
          verdict: 'PASS',
          score: 1,
          scored_at: '2026-10-07T12:00:00Z',
        },
      }),
    )
    const badge = screen.getByTestId('execution-eval-badge')
    expect(badge).toHaveAttribute('href', '/evals/eval-7f3a')
    expect(badge).toHaveTextContent('verifier-seed: case-1')
    expect(badge).toHaveTextContent('PASS')
  })

  it('shows no badge for an execution in no eval', () => {
    renderExecution(runOf({ eval: null }))
    expect(screen.queryByTestId('execution-eval-badge')).toBeNull()
  })

  it('shows no badge when the server predates the field', () => {
    renderExecution(runOf())
    expect(screen.queryByTestId('execution-eval-badge')).toBeNull()
  })
})
