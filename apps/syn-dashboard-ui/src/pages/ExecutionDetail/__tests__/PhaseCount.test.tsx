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
 * produce, so a card that measures the array fails.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ExecutionDetailResponse, PhaseExecutionDetail } from '../../../types'

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
    execution,
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
  it('counts the phases the workflow declared, not the ones that started', () => {
    renderExecution(diedInPhaseTwo())

    // "1/2" is the phase array measuring itself; the run had three phases.
    expect(metricCardValue('Phases')).toBe('1/3')
  })

  it('still reports the total when the run died before any phase reported', () => {
    renderExecution(diedInPhaseTwo({ phases: [], completed_phases: 0 }))

    // The worst case for the old code: "0/0", a run of no phases at all.
    expect(metricCardValue('Phases')).toBe('0/3')
  })

  it('says the total is unknown rather than substituting the phase tally', () => {
    // total_phases 0 means nothing told the page the count - a projection that
    // has not rebuilt. Rendering "1/2" here would restate the defect as fact.
    renderExecution(diedInPhaseTwo({ total_phases: 0 }))

    expect(metricCardValue('Phases')).toBe('1/—')
  })
})
