/**
 * The execution page renders against an API that predates the execution-level
 * cost fields (#897 / #2360): release 1.0.6 sends none of `total_cost_display`,
 * `cost_by_model`, `cost_by_model_display` or `unattributed_cost_display`.
 *
 * A newer dashboard in front of it used to throw on `model in costByModel` and
 * `Object.keys(execution.cost_by_model)` and render a blank page. Absent now
 * reads as no split and no display text: the em dash, never a dollar figure
 * the browser formatted from `total_cost_usd`.
 *
 * Every cost string the fixture does send is a sentinel without a `$`, so any
 * `$<digit>` on the page could only have been formatted client-side.
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

// Imported after the mock is registered so the page picks up the stub.
const { ExecutionDetail } = await import('../ExecutionDetail')

const EM_DASH = '—'

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
  completed_at: new Date().toISOString(),
  status: 'completed',
  model: null,
  cost_usd: '0.30566780000000005',
  cost_display: 'PHASE-COST',
  cost_by_model: {},
}

/** The shape release 1.0.6 serves: no execution-level cost text or split at all. */
const OLDER_API_EXECUTION = {
  workflow_execution_id: 'exec-older-api',
  phase_progress: { completed: 2, skipped: 0, possible: 2, remaining_possible: 0, percent: 100, display: '2 of 2 phases' },
  workflow_id: 'wf-1',
  workflow_name: 'Older API run',
  status: 'completed',
  started_at: new Date().toISOString(),
  completed_at: new Date().toISOString(),
  phases: [
    { ...PHASE, phase_id: 'phase-1', name: 'plan' },
    {
      ...PHASE,
      phase_id: 'phase-2',
      name: 'implement',
      unpriced_models: ['claude-fable-5-1'],
      unpriced_model_cost_display: 'UNPRICED-LABEL',
    },
  ],
  total_input_tokens: 0,
  total_output_tokens: 0,
  total_cache_creation_tokens: 0,
  total_cache_read_tokens: 0,
  total_tokens: 0,
  total_cost_usd: '0.6113356000000001',
  unpriced_observation_count: 0,
  artifact_ids: [],
  error_message: null,
  repos: [],
  total_duration_seconds: 0,
} as unknown as ExecutionDetailResponse // test fixture: the older wire shape, which the current type no longer requires to be complete

const NULL_COST_FIELDS = {
  total_cost_display: null,
  cost_by_model: null,
  cost_by_model_display: null,
  unattributed_cost_display: null,
} satisfies Partial<ExecutionDetailResponse>

function renderPage(execution: ExecutionDetailResponse) {
  useExecutionData.mockReturnValue({
    execution: withPlanOfPhases(execution),
    artifactDetails: {},
    loading: false,
    error: null,
    isConnected: true,
    now: Date.now(),
    refreshExecution: vi.fn(),
  })
  return render(
    <MemoryRouter initialEntries={['/executions/exec-older-api']}>
      <ExecutionDetail />
    </MemoryRouter>,
  )
}

describe.each([
  ['omits the cost fields', OLDER_API_EXECUTION],
  ['sends the cost fields as null', { ...OLDER_API_EXECUTION, ...NULL_COST_FIELDS }],
])('ExecutionDetail against an API that %s', (_, execution) => {
  it('renders the page and its phases', () => {
    const { container } = renderPage(execution)
    expect(screen.getAllByText('Older API run').length).toBeGreaterThan(0)
    expect(container.querySelector('#phase-timeline')?.textContent).toContain('plan')
    expect(container.querySelector('#phase-timeline')?.textContent).toContain('implement')
  })

  it('lists the unpriced model with no split, and the total as an em dash', () => {
    const { container } = renderPage(execution)
    const card = container.querySelector('#cost-by-model')
    expect(card?.textContent).toContain('UNPRICED-LABEL')
    expect(card?.textContent).toContain(EM_DASH)
    expect(screen.getByText('Total Cost').parentElement?.textContent).toContain(EM_DASH)
  })

  it('formats no dollar figure in the browser', () => {
    const { container } = renderPage(execution)
    expect(container.textContent).not.toMatch(/\$\s*\d/)
  })

  it('draws no Cost by Model card when nothing is unpriced either', () => {
    const phases = execution.phases.map((p) => ({ ...p, unpriced_models: [] }))
    const { container } = renderPage({ ...execution, phases })
    expect(screen.getAllByText('Older API run').length).toBeGreaterThan(0)
    expect(container.querySelector('#cost-by-model')).toBeNull()
  })
})

describe('ExecutionDetail with a split but no display text for it', () => {
  it('shows each row as an em dash, not a formatted amount', () => {
    const { container } = renderPage({
      ...OLDER_API_EXECUTION,
      cost_by_model: { 'claude-opus-5-5': '0.30566780000000005' },
      cost_by_model_display: null,
    })
    const card = container.querySelector('#cost-by-model')
    expect(card?.textContent).toContain(EM_DASH)
    expect(container.textContent).not.toMatch(/\$\s*\d/)
  })
})
