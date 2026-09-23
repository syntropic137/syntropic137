/**
 * What the agent SAID is shown, and shown as something the agent said (#1392).
 *
 * THE DEFECT. `failure_reason` went straight into `failure_classification`, so
 * a phase that exited cleanly and wrote `"task"` was drawn by this page as the
 * platform's own finding: amber "task failed", and out of the platform failure
 * count. The only thing corroborating that word is that the process exited and
 * its stream arrived intact, which is evidence about the HARNESS. So a run that
 * had simply given up could label itself and be believed.
 *
 * THE FIX HAS TWO HALVES AND BOTH ARE ASSERTED HERE, because either alone is a
 * different bug. The word must still REACH an operator - dropping it would
 * throw away the most useful thing in the record, and it is what #1392 left
 * undone for a release, with the value stopping at the domain read models and
 * never crossing into the API or this page. And it must arrive as ATTRIBUTION -
 * if it still picked the colour or the heading, it would still be an
 * uncorroborated claim rendered as a measurement, which is the defect itself.
 *
 * The control is the run that named no cause. It proves the quotation is drawn
 * from the response rather than printed for every failure, which a test with
 * only the reporting run would not distinguish.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  ExecutionDetailResponse,
  PhaseExecutionDetail,
  ReportedFailureReason,
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

const EXECUTION_ID = 'exec-1392'

/**
 * The prose the failing phase wrote, which says nothing about which KIND of
 * failure it was.
 *
 * Deliberately unclassifiable by eye: if this sentence named the cause, a page
 * that dropped `reported_failure_reason` entirely could still be argued to
 * have told the operator, and the assertions below would be about the fixture.
 */
const ERROR_MESSAGE = 'Phase implement reported success=false: stopping here.'

function failedPhase(): PhaseExecutionDetail {
  return {
    workflow_phase_id: 'phase-1',
    name: 'implement',
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

/**
 * A run the platform measured as a correct refusal, whose phase reported this.
 *
 * `failure_classification` is held at `correct_refusal` across every case, so
 * the only thing varying is the word the agent wrote. That is what makes the
 * colour assertions below mean something: a difference in tone between these
 * fixtures could only have come from the report.
 */
function reportingExecution(
  reported_failure_reason: ReportedFailureReason | null,
): ExecutionDetailResponse {
  return {
    workflow_execution_id: EXECUTION_ID,
    workflow_id: 'wf-1392',
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
    error_message: ERROR_MESSAGE,
    failure_classification: 'correct_refusal',
    reported_failure_reason,
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
  await screen.findByText(ERROR_MESSAGE)
  return container
}

/** Every element inside `scope` drawn in any shade of failure red. */
function redWithin(scope: HTMLElement): Element[] {
  return Array.from(scope.querySelectorAll('[class*="red-"]'))
}

describe('the word the agent wrote, on the page an operator opens', () => {
  it('shows it, attributed to the agent', async () => {
    await renderPage(reportingExecution('task'))

    expect(screen.getByText(/The agent reported: task/)).toBeTruthy()
  })

  it('explains what the word means, so the operator need not know the vocabulary', async () => {
    await renderPage(reportingExecution('task'))

    expect(
      screen.getByText(/the request was wrong, impossible, or too big for one phase/),
    ).toBeTruthy()
  })

  it('shows the word for "I could not tell" as the agent saying it', async () => {
    await renderPage(reportingExecution('unknown'))

    expect(screen.getByText(/The agent reported: unknown/)).toBeTruthy()
  })

  it('quotes nothing for a phase that named no cause', async () => {
    await renderPage(reportingExecution(null))

    expect(screen.queryByText(/The agent reported/)).toBeNull()
  })

  it('does not let the reported word turn the page red', async () => {
    // `platform` is the word an agent would write to call the machinery
    // broken. Believing it here is exactly the promotion #1392 refuses: the
    // measurement beside it says correct_refusal, and the colour follows the
    // measurement.
    const { length: redForPlatform } = redWithin(await renderPage(reportingExecution('platform')))

    expect(redForPlatform).toBe(0)
  })

  it('draws the same run the same way whatever the agent called it', async () => {
    const reported = redWithin(await renderPage(reportingExecution('task'))).length
    const silent = redWithin(await renderPage(reportingExecution(null))).length

    expect(reported).toBe(silent)
  })
})
