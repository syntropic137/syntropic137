/**
 * A refused run must not be reported as a broken one on its detail page
 * (#1367).
 *
 * This page said it three ways at once: a red "Execution Failed" card, a red
 * failed-phase card in the timeline, and - since #1357 - an amber `refused`
 * badge in the header contradicting both. "Execution Failed" is a claim about
 * the PLATFORM, and a phase that read its own work and judged it not
 * deliverable is the platform working.
 *
 * The whole page is the scope of the colour assertion rather than the error
 * card, because the timeline below it was red for the same run and for the
 * same reason. The platform-failure fixture is the control: it must still be
 * red and must still say "Execution Failed".
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  ExecutionDetailResponse,
  FailureClassification,
  PhaseExecutionDetail,
} from '../../../types'

vi.mock('../../../api/executions', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/executions')>()),
  getExecution: vi.fn(),
}))
// jsdom has no EventSource, and what the stream reports is not the subject.
vi.mock('../../../hooks/useExecutionStream', () => ({
  useExecutionStream: vi.fn(() => ({ isConnected: true })),
}))

const { getExecution } = await import('../../../api/executions')
const { ExecutionDetail } = await import('../ExecutionDetail')

const EXECUTION_ID = 'exec-1'
const REFUSAL_MESSAGE = 'Phase review reported success=false: the deliverable is not acceptable'

function failedPhase(): PhaseExecutionDetail {
  return {
    workflow_phase_id: 'phase-1',
    name: 'review',
    status: 'failed',
    session_id: null,
    agent_session_id: null,
    artifact_id: null,
    input_tokens: 10,
    output_tokens: 20,
    cache_creation_tokens: 0,
    cache_read_tokens: 0,
    duration_seconds: 5,
    cost_usd: 0,
    unpriced_observation_count: 0,
    started_at: '2026-09-18T00:00:00Z',
    completed_at: '2026-09-18T00:05:00Z',
    model: null,
    cost_by_model: {},
  }
}

function failedExecution(
  failure_classification: FailureClassification,
): ExecutionDetailResponse {
  return {
    workflow_execution_id: EXECUTION_ID,
    workflow_id: 'wf-1',
    workflow_name: 'Nightly',
    status: 'failed',
    started_at: '2026-09-18T00:00:00Z',
    completed_at: '2026-09-18T00:05:00Z',
    phases: [failedPhase()],
    total_phases: 1,
    completed_phases: 0,
    total_input_tokens: 10,
    total_output_tokens: 20,
    total_cache_creation_tokens: 0,
    total_cache_read_tokens: 0,
    total_tokens: 30,
    total_cost_usd: 0,
    unpriced_observation_count: 0,
    artifact_ids: [],
    error_message: REFUSAL_MESSAGE,
    failure_classification,
    repos: [],
    workspace: null,
  }
}

beforeEach(() => {
  vi.mocked(getExecution).mockReset()
})

async function renderPage(execution: ExecutionDetailResponse): Promise<HTMLElement> {
  vi.mocked(getExecution).mockResolvedValue(execution)
  const { container } = render(
    <MemoryRouter initialEntries={[`/executions/${EXECUTION_ID}`]}>
      <Routes>
        <Route path="/executions/:executionId" element={<ExecutionDetail />} />
      </Routes>
    </MemoryRouter>,
  )
  await screen.findByText(REFUSAL_MESSAGE)
  return container
}

/** Every element inside `scope` drawn in any shade of failure red. */
function redWithin(scope: HTMLElement): Element[] {
  return Array.from(scope.querySelectorAll('[class*="red-"]'))
}

describe('the execution detail page and the kind of failure', () => {
  it('does not report a refused run as a failed execution', async () => {
    await renderPage(failedExecution('correct_refusal'))

    expect(screen.queryByText('Execution Failed')).toBeNull()
    expect(screen.getByText('Phase Reported Failure')).toBeTruthy()
  })

  it('draws nothing on the page of a refused run red', async () => {
    const container = await renderPage(failedExecution('correct_refusal'))

    expect(redWithin(container)).toEqual([])
  })

  it('still keeps the refusal on screen, in amber', async () => {
    // A page that says nothing is not a fix: the operator still has to be
    // told the run did not deliver, and told it on the card that carries the
    // message rather than anywhere amber happens to appear.
    await renderPage(failedExecution('correct_refusal'))

    const card = screen.getByText(REFUSAL_MESSAGE).closest('[class*="amber-"]')
    expect(card).not.toBeNull()
  })

  it('still reports a platform failure as a failed execution, in red', async () => {
    const container = await renderPage(failedExecution('platform'))

    expect(screen.getByText('Execution Failed')).toBeTruthy()
    expect(redWithin(container).length).toBeGreaterThan(0)
  })
})
