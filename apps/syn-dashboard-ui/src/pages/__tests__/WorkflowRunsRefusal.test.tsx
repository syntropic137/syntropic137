/**
 * A correct refusal must not be drawn as an outage on Workflow Runs (#1367).
 *
 * This is the surface a prop could not fix. `/workflows/{id}/runs` never sent
 * `failure_classification` at all, so every refused run on this page was plain
 * red however well the badge understood the difference - the fix is a field on
 * `ExecutionRunSummary` as much as it is a component change.
 *
 * Served over `fetch` rather than by mocking the hook, because the field
 * arriving from the server is half of what is being asserted: a test handed
 * the classification directly would pass against the API that never sends it.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { FailureClassification, WorkflowExecutionSummary, WorkflowResponse } from '../../types'
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
  runs_count: 2,
  runs_link: null,
}

function failedRun(
  id: string,
  failure_classification: FailureClassification,
): WorkflowExecutionSummary {
  return {
    workflow_execution_id: id,
    workflow_id: WORKFLOW_ID,
    status: 'failed',
    started_at: '2026-09-18T00:00:00Z',
    completed_at: '2026-09-18T00:05:00Z',
    completed_phases: 1,
    total_phases: 2,
    total_tokens: 100,
    total_cost_usd: 0,
    failure_classification,
  }
}

const REFUSED_RUN = failedRun('refused0-0000-0000-0000-000000000000', 'correct_refusal')
const BROKEN_RUN = failedRun('broken00-0000-0000-0000-000000000000', 'platform')

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  vi.stubGlobal('fetch', async (input: RequestInfo | URL): Promise<Response> => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    if (url.endsWith(`/workflows/${WORKFLOW_ID}/runs`)) {
      return json({ runs: [REFUSED_RUN, BROKEN_RUN] })
    }
    if (url.endsWith(`/workflows/${WORKFLOW_ID}`)) return json(WORKFLOW)
    throw new Error(`No fake endpoint for ${url}`)
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/workflows/${WORKFLOW_ID}/runs`]}>
      <Routes>
        <Route path="/workflows/:workflowId/runs" element={<WorkflowRuns />} />
      </Routes>
    </MemoryRouter>,
  )
}

/** The rendered row for a run. Throws if the page has none. */
async function rowFor(run: WorkflowExecutionSummary): Promise<HTMLElement> {
  const shortId = run.workflow_execution_id.slice(0, 8)
  const cell = await screen.findByText(`${shortId}...`)
  const row = cell.closest('a')
  if (!row) throw new Error(`No row for ${shortId}`)
  return row
}

/** Every element inside `scope` drawn in any shade of failure red. */
function redWithin(scope: HTMLElement): Element[] {
  return Array.from(scope.querySelectorAll('[class*="red-"]'))
}

describe('Workflow Runs and the kind of failure', () => {
  it('draws nothing in a refused run red', async () => {
    renderPage()

    expect(redWithin(await rowFor(REFUSED_RUN))).toEqual([])
  })

  it('colours the refused run amber rather than leaving it uncoloured', async () => {
    renderPage()
    const row = await rowFor(REFUSED_RUN)

    expect(row.querySelectorAll('[class*="amber-"]').length).toBeGreaterThan(0)
    expect(row.textContent).toContain('refused')
  })

  it('still draws a platform failure red on the same page', async () => {
    renderPage()

    expect(redWithin(await rowFor(BROKEN_RUN)).length).toBeGreaterThan(0)
  })
})
