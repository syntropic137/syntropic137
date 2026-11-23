/**
 * The execution page's Cost by Model card reads the execution's own
 * `cost_by_model` and the API's text for it (#897), not a sum of the phases'
 * maps formatted in the browser.
 *
 * The only phase is still running, so its map is empty: a card built from the
 * phases would not render at all. Only the execution-level fields carry these
 * rows and these strings.
 */

import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ExecutionDetailResponse } from '../../../types'
import { withPlanOfPhases } from '../../../test/phasePlanFixtures'

const useExecutionData = vi.fn()

vi.mock('../../../hooks', () => ({
  useExecutionData: (executionId: string | undefined) => useExecutionData(executionId),
}))

// Imported after the mock is registered so the page picks up the stub.
const { ExecutionDetail } = await import('../ExecutionDetail')

const EXECUTION = {
  workflow_execution_id: 'exec-897',
  phase_progress: { completed: 0, skipped: 0, possible: 1, remaining_possible: 1, percent: 0, display: 'phase 1 of up to 1' },
  workflow_id: 'wf-1',
  workflow_name: 'Live run',
  status: 'running',
  started_at: new Date().toISOString(),
  completed_at: null,
  phases: [
    {
      phase_id: 'phase-1',
      name: 'implement',
      status: 'running',
      session_id: 'sess-1',
      agent_session_id: null,
      artifact_id: null,
      input_tokens: 0,
      output_tokens: 0,
      cache_creation_tokens: 0,
      cache_read_tokens: 0,
      duration_seconds: 0,
      cost_usd: '0',
      cost_display: '$0.00',
      unpriced_observation_count: 0,
      started_at: new Date().toISOString(),
      completed_at: null,
      model: null,
      cost_by_model: {},
    },
  ],
  total_input_tokens: 0,
  total_output_tokens: 0,
  total_cache_creation_tokens: 0,
  total_cache_read_tokens: 0,
  total_tokens: 0,
  total_cost_usd: '0.43809100000000005',
  total_cost_display: 'EXECUTION-TOTAL',
  cost_by_model: { 'claude-opus-5-5': '0.30566780000000005' },
  cost_by_model_display: { 'claude-opus-5-5': 'EXECUTION-OPUS' },
  unattributed_cost_display: 'EXECUTION-REMAINDER',
  unpriced_observation_count: 0,
  artifact_ids: [],
  error_message: null,
  repos: [],
  total_duration_seconds: 0,
} as unknown as ExecutionDetailResponse // test fixture: only the fields the page reads

describe('ExecutionDetail Cost by Model card', () => {
  it("renders the execution's cost_by_model with the API's text", () => {
    useExecutionData.mockReturnValue({
      execution: withPlanOfPhases(EXECUTION),
      artifactDetails: {},
      loading: false,
      error: null,
      isConnected: true,
      now: Date.now(),
      refreshExecution: vi.fn(),
    })
    const { container } = render(
      <MemoryRouter initialEntries={['/executions/exec-897']}>
        <ExecutionDetail />
      </MemoryRouter>,
    )
    const card = container.querySelector('#cost-by-model')
    expect(card?.textContent).toContain('EXECUTION-TOTAL')
    expect(card?.textContent).toContain('EXECUTION-OPUS')
    expect(card?.textContent).toContain('EXECUTION-REMAINDER')
  })
})
