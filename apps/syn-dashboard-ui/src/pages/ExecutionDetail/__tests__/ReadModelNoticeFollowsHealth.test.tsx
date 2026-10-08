/**
 * The detail page's rebuilding notice follows the shell's measured `/health`
 * answer, not the response snapshot it was loaded with.
 *
 * A terminal execution stops refreshing, so its `read_model_status` is frozen
 * at whatever the read model was doing when the page loaded. Preferring that
 * snapshot kept "rebuilding" on screen after the global banner had cleared;
 * the converse is a healthy snapshot that must still show a rebuild that
 * starts later. Before `/health` has answered, the snapshot is the only
 * verdict there is and must still be shown.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  HEALTHY_READ_PATH,
  ReadPathHealthContext,
  UNMEASURED_READ_PATH,
  type ReadPathHealth,
} from '../../../hooks/useReadPathHealth'
import { REBUILDING_EXECUTIONS } from '../../../test/readPathFixtures'
import type { ReadModelStatus } from '../../../types'

const useExecutionData = vi.fn()
vi.mock('../../../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../hooks')>()),
  useExecutionData: () => useExecutionData(),
}))

const { ExecutionDetail } = await import('../ExecutionDetail')

const DETAILS_REBUILDING: ReadModelStatus = {
  ...REBUILDING_EXECUTIONS,
  projection: 'workflow_execution_details',
  label_display: 'execution details',
}

function completedExecution(readModelStatus: ReadModelStatus | null) {
  return {
    workflow_execution_id: 'exec-review',
    workflow_id: 'wf-review',
    workflow_name: 'Review',
    status: 'completed',
    started_at: '2026-10-08T02:00:00Z',
    completed_at: '2026-10-08T02:01:00Z',
    phases: [],
    phase_plan: [],
    total_phases: 0,
    completed_phases: 0,
    phase_progress: { completed: 0, skipped: 0, possible: 0, remaining_possible: 0, percent: 100, display: '0 of 0' },
    total_input_tokens: 0,
    total_output_tokens: 0,
    total_cache_creation_tokens: 0,
    total_cache_read_tokens: 0,
    total_tokens: 0,
    total_cost_usd: 0,
    unpriced_observation_count: 0,
    artifact_ids: [],
    error_message: null,
    repos: [],
    total_duration_seconds: 60,
    read_model_status: readModelStatus,
  }
}

function serve(readModelStatus: ReadModelStatus | null) {
  // A terminal execution: the data hook stops refreshing, so this snapshot never changes.
  useExecutionData.mockReturnValue({
    execution: completedExecution(readModelStatus),
    artifactDetails: {},
    loading: false,
    error: null,
    isConnected: true,
    now: Date.now(),
    refreshExecution: vi.fn(),
  })
}

function page(readPath: ReadPathHealth) {
  return (
    <MemoryRouter>
      <ReadPathHealthContext.Provider value={readPath}>
        <ExecutionDetail />
      </ReadPathHealthContext.Provider>
    </MemoryRouter>
  )
}

describe('ExecutionDetail read model notice', () => {
  beforeEach(() => vi.clearAllMocks())

  it('clears a rebuilding snapshot once the shell measures catch-up', () => {
    serve(DETAILS_REBUILDING)
    const view = render(page({ ...HEALTHY_READ_PATH, rebuilding: [DETAILS_REBUILDING] }))
    expect(screen.getByTestId('read-model-notice')).toHaveTextContent('while execution details is rebuilt')

    view.rerender(page(HEALTHY_READ_PATH))
    expect(screen.queryByTestId('read-model-notice')).toBeNull()
  })

  it('shows a rebuild that starts after a healthy snapshot was loaded', () => {
    serve(null)
    const view = render(page(HEALTHY_READ_PATH))
    expect(screen.queryByTestId('read-model-notice')).toBeNull()

    view.rerender(page({ ...HEALTHY_READ_PATH, rebuilding: [DETAILS_REBUILDING] }))
    expect(screen.getByTestId('read-model-notice')).toHaveTextContent('while execution details is rebuilt')
  })

  it("shows the response's own verdict before /health has been measured", () => {
    serve(DETAILS_REBUILDING)
    render(page(UNMEASURED_READ_PATH))
    expect(screen.getByTestId('read-model-notice')).toHaveTextContent('while execution details is rebuilt')
  })
})
