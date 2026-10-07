/**
 * The Phases card must count the phases the run set out to do (#1147).
 *
 * `phases` holds the phases that STARTED. Measuring the denominator with it
 * rendered a three-phase run that died in phase one as "1/2" - or "0/1" for
 * one that died before its first phase reported - so the phases that never ran
 * were indistinguishable from phases the workflow never had. The count comes
 * from the WorkflowExecutionStarted event and now reaches the page, having
 * previously been dropped at every hop between the projection and this card.
 *
 * Every fixture here sets `total_phases` to a number `phases.length` cannot
 * produce, so a card that measures the array fails. The card now renders the
 * API's `phase_progress.display`, which also drops repair rounds a certifying
 * review skipped (PC-63), so a card that divides the raw counts fails too.
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
    workflow_phase_id: name,
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
function diedInPhaseTwo(
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

/** MetricCard renders title, value and subtitle as consecutive paragraphs. */
function metricCardValue(title: string): string {
  return screen.getByText(title).nextElementSibling?.textContent ?? ''
}

beforeEach(() => {
  useExecutionData.mockReset()
})

describe('ExecutionDetail phase count', () => {
  it('renders the API progress, not the phase array measuring itself', () => {
    renderExecution(diedInPhaseTwo())

    // "1/2" is the phase array measuring itself; the run had three phases.
    expect(metricCardValue('Phases')).toBe('1 of up to 3, failed')
  })

  it('does not divide completed by total when review rounds were skipped', () => {
    // PC-63: a run certified at its first review completes 6 of its 10
    // defined phases. Dividing the raw counts rendered "6/10", a finished run
    // that looked four phases short; the API says what actually happened.
    renderExecution(
      diedInPhaseTwo({
        status: 'completed',
        total_phases: 10,
        completed_phases: 6,
        phase_progress: {
          completed: 6,
          skipped: 4,
          possible: 6,
          remaining_possible: 0,
          percent: 100,
          display: '6 of 6 (4 phases not needed)',
        },
      }),
    )

    expect(metricCardValue('Phases')).toBe('6 of 6 (4 phases not needed)')
  })
})
