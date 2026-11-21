/**
 * Each row on Workflow Runs shows the cost the API rendered for it (#897).
 *
 * Served over `fetch`, like WorkflowRunsRefusal, because the fields arriving
 * from `/workflows/{id}/runs` are half of what is asserted: a row handed them
 * directly would pass against a client that drops them.
 */

import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ANY_UNPRICED_NOTE, COST_COVERAGE_CASES } from '../../test/costCoverageFixtures'
import type { WorkflowExecutionSummary, WorkflowResponse } from '../../types'
import { WorkflowRuns } from '../WorkflowRuns'

const WORKFLOW_ID = 'wf-1'

const WORKFLOW: WorkflowResponse = {
  id: WORKFLOW_ID,
  name: 'Nightly',
  description: null,
  workflow_type: 'sequential',
  classification: 'standard',
  phases: [],
  input_declarations: [],
  created_at: null,
  runs_count: 1,
  runs_link: null,
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe.each(COST_COVERAGE_CASES)('Workflow Runs row cost, $name', (c) => {
  const run: WorkflowExecutionSummary = {
    workflow_execution_id: 'run00000-0000-0000-0000-000000000000',
    workflow_id: WORKFLOW_ID,
    status: 'completed',
    started_at: '2026-11-21T00:00:00Z',
    completed_at: '2026-11-21T00:05:00Z',
    completed_phases: 1,
    phase_progress: { completed: 1, skipped: 0, possible: 1, remaining_possible: 0, percent: 100, display: '1 of 1' },
    total_phases: 1,
    total_tokens: 30,
    total_cost_usd: c.total_cost_usd,
    total_cost_display: c.total_cost_display,
    unpriced_observation_count: c.unpriced_observation_count,
  }

  beforeEach(() => {
    vi.stubGlobal('fetch', async (input: RequestInfo | URL): Promise<Response> => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.endsWith(`/workflows/${WORKFLOW_ID}/runs`)) return json({ runs: [run] })
      if (url.endsWith(`/workflows/${WORKFLOW_ID}`)) return json(WORKFLOW)
      throw new Error(`No fake endpoint for ${url}`)
    })
  })

  it('shows the API display and the coverage note only when something was unpriced', async () => {
    render(
      <MemoryRouter initialEntries={[`/workflows/${WORKFLOW_ID}/runs`]}>
        <Routes>
          <Route path="/workflows/:workflowId/runs" element={<WorkflowRuns />} />
        </Routes>
      </MemoryRouter>,
    )
    const row = (await screen.findByText('run00000...')).closest('a')
    if (!row) throw new Error('No row for the run')

    expect(within(row).getByText(c.shows)).toBeTruthy()
    if (c.note) expect(within(row).getByText(c.note)).toBeTruthy()
    else expect(within(row).queryByText(ANY_UNPRICED_NOTE)).toBeNull()
  })
})
