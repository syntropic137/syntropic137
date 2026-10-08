/**
 * Eval runs on the Executions list: a badge on the row, and a filter.
 *
 * Owner feedback (2026-10-08): "the executions table should have some sort of
 * badge if it's an eval". The execution page had one; the list did not, so an
 * eval run and an ordinary SDLC run looked identical until opened.
 *
 * The rows reach the page through `fetch` from the same double the paging
 * tests use, so the `eval` field has to survive every hop the page owns -
 * the response, `toExecutionListItem`, the column and the card - to be seen.
 * Dropping it at any one of them leaves these rows badgeless.
 */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ExecutionEvalRun } from '../../../api/evals'
import { serveListEndpoint } from '../../../test/fakeListServer'
import { EXECUTIONS, matchesExecutionSearch } from '../../../test/listFixtures'
import { ExecutionCard } from '../ExecutionCard'
import { ExecutionList } from '../ExecutionList'

vi.mock('../../../hooks/useActivityStream', () => ({
  useActivityStream: vi.fn(() => ({ connected: true, lastEventAt: null })),
}))

const LONG_NAME = 'verifier-seed: a deliberately long eval name that cannot fit a phone row'

function evalRun(overrides: Partial<ExecutionEvalRun> = {}): ExecutionEvalRun {
  return {
    eval_id: 'eval-7f3a',
    eval_name: 'verifier-seed: case-1',
    association_kind: 'launched',
    verdict: 'PASS',
    score: 1,
    scored_at: '2026-10-07T12:00:00Z',
    ...overrides,
  }
}

// Rows 0-2 are the youngest in the shared fixture, so all sit inside the
// default 24h window without the test touching it.
const SCORED = {
  ...EXECUTIONS[0],
  workflow_execution_id: 'exec-scored',
  workflow_name: 'Scored eval run',
  eval: evalRun(),
}
const UNSCORED = {
  ...EXECUTIONS[1],
  workflow_execution_id: 'exec-unscored',
  workflow_name: 'Unscored eval run',
  eval: evalRun({ eval_id: 'eval-9b1c', eval_name: LONG_NAME, verdict: null, score: null, scored_at: null }),
}
const ORDINARY = {
  ...EXECUTIONS[2],
  workflow_execution_id: 'exec-ordinary',
  workflow_name: 'Ordinary SDLC run',
  eval: null,
}

const server = serveListEndpoint({
  path: '/api/v1/executions',
  collection: [SCORED, UNSCORED, ORDINARY],
  matchesSearch: matchesExecutionSearch,
})

function renderPage(url = '/executions') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <ExecutionList />
    </MemoryRouter>,
  )
}

/** The rendered table row for a workflow name. */
async function rowFor(workflowName: string): Promise<HTMLElement> {
  await screen.findByText(workflowName)
  const rows = Array.from(screen.getByRole('table').querySelectorAll('tbody tr'))
  const row = rows.find((candidate) => candidate.textContent?.includes(workflowName))
  if (!(row instanceof HTMLElement)) throw new Error(`No row for ${workflowName}`)
  return row
}

describe('Eval badge on the Executions table', () => {
  it('names the eval, links to it, and shows the verdict on a scored run', async () => {
    renderPage()

    const badge = within(await rowFor('Scored eval run')).getByTestId('execution-eval-badge')

    expect(badge).toHaveAttribute('href', '/evals/eval-7f3a')
    expect(badge).toHaveTextContent('verifier-seed: case-1')
    expect(within(badge).getByText('PASS')).toHaveAttribute('data-verdict', 'PASS')
  })

  it('marks an unscored eval run Unscored, with its name truncated rather than wrapped', async () => {
    renderPage()

    const badge = within(await rowFor('Unscored eval run')).getByTestId('execution-eval-badge')

    expect(badge).toHaveAttribute('href', '/evals/eval-9b1c')
    expect(within(badge).getByText('Unscored')).toHaveAttribute('data-verdict', 'UNSCORED')
    expect(within(badge).getByText(LONG_NAME)).toHaveClass('truncate')
  })

  it('gives a run in no eval no badge at all', async () => {
    renderPage()

    const row = await rowFor('Ordinary SDLC run')

    expect(within(row).queryByTestId('execution-eval-badge')).toBeNull()
    expect(screen.getAllByTestId('execution-eval-badge')).toHaveLength(2)
  })

  it('opens the eval, not the execution, when the badge is clicked', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/executions']}>
        <Routes>
          <Route path="/executions" element={<ExecutionList />} />
          <Route path="/executions/:id" element={<p>execution page</p>} />
          <Route path="/evals/:id" element={<p>eval page</p>} />
        </Routes>
      </MemoryRouter>,
    )

    const badge = within(await rowFor('Scored eval run')).getByTestId('execution-eval-badge')
    // The row is itself a link to the execution; the badge must win.
    await user.click(badge)

    expect(screen.getByText('eval page')).toBeInTheDocument()
    expect(screen.queryByText('execution page')).toBeNull()
  })
})

describe('Eval badge on the narrow-screen card', () => {
  it('renders on an eval run and not on an ordinary one', () => {
    const { rerender } = render(
      <MemoryRouter>
        <ExecutionCard exec={{ ...UNSCORED, total_cost_usd: 0, completed_at: null, repos_display: null }} />
      </MemoryRouter>,
    )
    const badge = screen.getByTestId('execution-eval-badge')
    expect(badge).toHaveClass('max-w-full')
    expect(within(badge).getByText(LONG_NAME)).toHaveClass('truncate')

    rerender(
      <MemoryRouter>
        <ExecutionCard exec={{ ...ORDINARY, total_cost_usd: 0, completed_at: null, repos_display: null }} />
      </MemoryRouter>,
    )
    expect(screen.queryByTestId('execution-eval-badge')).toBeNull()
  })
})

describe('Evals only / Hide evals', () => {
  it('asks the server for nothing about evals by default', async () => {
    renderPage()
    await screen.findByText('Scored eval run')

    expect(server.lastRequest.params.has('in_eval')).toBe(false)
  })

  it.each([
    ['Evals only', 'true'],
    ['Hide evals', 'false'],
  ])('"%s" sends in_eval=%s and returns to page 1', async (label, wire) => {
    const user = userEvent.setup()
    renderPage('/executions?page=2')
    await screen.findByText('Scored eval run')

    await user.click(screen.getByRole('button', { name: label }))

    expect(screen.getByRole('button', { name: label })).toHaveAttribute('aria-pressed', 'true')
    expect(server.lastRequest.params.get('in_eval')).toBe(wire)
    expect(server.lastRequest.params.get('page')).toBe('1')
  })

  it('pressing the active chip again shows every run', async () => {
    const user = userEvent.setup()
    renderPage('/executions?evals=hide')
    await screen.findByText('Ordinary SDLC run')
    expect(server.lastRequest.params.get('in_eval')).toBe('false')

    await user.click(screen.getByRole('button', { name: 'Hide evals' }))

    expect(screen.getByRole('button', { name: 'Hide evals' })).toHaveAttribute('aria-pressed', 'false')
    expect(server.lastRequest.params.has('in_eval')).toBe(false)
  })

  it('is cleared by Reset with the other filters', async () => {
    const user = userEvent.setup()
    renderPage('/executions?evals=only')
    await screen.findByText('Scored eval run')

    await user.click(screen.getByRole('button', { name: 'Reset' }))

    expect(screen.getByRole('button', { name: 'Evals only' })).toHaveAttribute('aria-pressed', 'false')
    expect(server.lastRequest.params.has('in_eval')).toBe(false)
  })
})
