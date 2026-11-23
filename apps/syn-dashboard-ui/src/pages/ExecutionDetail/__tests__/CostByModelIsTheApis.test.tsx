/**
 * The execution page's Cost by Model card reads the execution's own
 * `cost_by_model` and the API's text for it (#897), not a sum of the phases'
 * maps formatted in the browser.
 *
 * The shape the API sends mid-run: phase 1 completed with its split, phase 2
 * is still running so its map is empty, and the execution's map is their sum
 * (`sum_cost_by_model` in routes/executions/queries.py). The total already
 * counts phase 2, so the API sends a remainder.
 *
 * The amounts and the shape are the producer's; the display strings are
 * sentinels no formatter produces, so they can only reach the card from the
 * execution-level display fields.
 */

import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { components } from '../../../generated/api-types'
import type { ExecutionDetailResponse } from '../../../types'
import { withPlanOfPhases } from '../../../test/phasePlanFixtures'

const useExecutionData = vi.fn()

vi.mock('../../../hooks', () => ({
  useExecutionData: (executionId: string | undefined) => useExecutionData(executionId),
}))

// Imported after the mock is registered so the page picks up the stub.
const { ExecutionDetail } = await import('../ExecutionDetail')

type Schemas = components['schemas']

const COMPLETED_PHASE_COST = {
  cost_usd: '0.30566780000000005',
  cost_display: '$0.31',
  cost_by_model: { 'claude-opus-5-5': '0.30566780000000005' },
} satisfies Pick<Schemas['PhaseExecutionInfo'], 'cost_usd' | 'cost_display' | 'cost_by_model'>

const RUNNING_PHASE_COST = {
  cost_usd: '0.1324232',
  cost_display: '$0.13',
  cost_by_model: {},
} satisfies Pick<Schemas['PhaseExecutionInfo'], 'cost_usd' | 'cost_display' | 'cost_by_model'>

const EXECUTION_COST = {
  total_cost_usd: '0.43809100000000005',
  total_cost_display: 'EXECUTION-TOTAL',
  // sum_cost_by_model over the two phases above.
  cost_by_model: { 'claude-opus-5-5': '0.30566780000000005' },
  cost_by_model_display: { 'claude-opus-5-5': 'EXECUTION-OPUS' },
  unattributed_cost_display: 'EXECUTION-REMAINDER',
} satisfies Pick<
  Schemas['ExecutionDetailResponse'],
  'total_cost_usd' | 'total_cost_display' | 'cost_by_model' | 'cost_by_model_display' | 'unattributed_cost_display'
>

const PHASE = {
  session_id: null,
  agent_session_id: null,
  artifact_id: null,
  input_tokens: 0,
  output_tokens: 0,
  cache_creation_tokens: 0,
  cache_read_tokens: 0,
  duration_seconds: 0,
  unpriced_observation_count: 0,
  started_at: new Date().toISOString(),
  model: null,
}

const EXECUTION = {
  workflow_execution_id: 'exec-897',
  phase_progress: { completed: 1, skipped: 0, possible: 2, remaining_possible: 1, percent: 50, display: 'phase 2 of up to 2' },
  workflow_id: 'wf-1',
  workflow_name: 'Live run',
  status: 'running',
  started_at: new Date().toISOString(),
  completed_at: null,
  phases: [
    {
      ...PHASE,
      ...COMPLETED_PHASE_COST,
      phase_id: 'phase-1',
      name: 'plan',
      status: 'completed',
      completed_at: new Date().toISOString(),
    },
    {
      ...PHASE,
      ...RUNNING_PHASE_COST,
      phase_id: 'phase-2',
      name: 'implement',
      status: 'running',
      completed_at: null,
    },
  ],
  total_input_tokens: 0,
  total_output_tokens: 0,
  total_cache_creation_tokens: 0,
  total_cache_read_tokens: 0,
  total_tokens: 0,
  ...EXECUTION_COST,
  unpriced_observation_count: 0,
  artifact_ids: [],
  error_message: null,
  repos: [],
  total_duration_seconds: 0,
} as unknown as ExecutionDetailResponse // test fixture: the cost fields are checked above; the rest are only what the page reads

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
