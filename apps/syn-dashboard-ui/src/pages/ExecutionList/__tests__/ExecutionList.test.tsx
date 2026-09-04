/**
 * Executions page against a server that really filters and pages (#1159).
 *
 * These assertions are all about the page an operator sees, not about the
 * hook's return value, because every one of the bugs they cover was a value
 * that existed correctly one hop earlier: the server sent `total` and
 * `status_counts`, and the browser rendered `rows.length` instead.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { answerListQuery } from '../../../test/fakeListServer'
import type { ListQuery } from '../../../api/listQuery'
import { ExecutionList } from '../ExecutionList'

vi.mock('../../../api/executions', () => ({ listAllExecutions: vi.fn() }))
vi.mock('../../../hooks/useActivityStream', () => ({
  useActivityStream: vi.fn(() => ({ connected: true, lastEventAt: null })),
}))

import { listAllExecutions } from '../../../api/executions'

const mockList = vi.mocked(listAllExecutions)

const HOUR_MS = 60 * 60 * 1000

interface FakeExecution {
  workflow_execution_id: string
  workflow_id: string
  workflow_name: string
  status: string
  started_at: string
  completed_at: string | null
  completed_phases: number
  total_phases: number
  total_tokens: number
  total_tokens_display: string
  total_input_tokens: number
  total_output_tokens: number
  total_cache_creation_tokens: number
  total_cache_read_tokens: number
  total_cost_usd: string
  total_cost_display: string
  unpriced_observation_count: number
  duration_seconds: number | null
  duration_display: string
  tool_call_count: number
  repos: string[]
}

function makeExecution(index: number, hoursAgo: number, status: string): FakeExecution {
  return {
    workflow_execution_id: `exec-${String(index).padStart(3, '0')}`,
    workflow_id: 'wf-1',
    workflow_name: `Run ${String(index).padStart(3, '0')}`,
    status,
    started_at: new Date(Date.now() - hoursAgo * HOUR_MS).toISOString(),
    completed_at: null,
    completed_phases: 1,
    total_phases: 1,
    total_tokens: 10,
    total_tokens_display: '10',
    total_input_tokens: 5,
    total_output_tokens: 5,
    total_cache_creation_tokens: 0,
    total_cache_read_tokens: 0,
    total_cost_usd: '0',
    total_cost_display: '$0.00',
    unpriced_observation_count: 0,
    duration_seconds: 1,
    duration_display: '1s',
    tool_call_count: 0,
    repos: [],
  }
}

/**
 * 360 executions, newest first, laid out so each window sees a different set:
 *   0-39     within the last 24h  (the default window)
 *   40-199   1-7 days old         (visible at 7d, not at 24h)
 *   200-359  older than 7 days    (visible only at "All")
 * Statuses are dealt so `completed` dominates by far more than one page holds.
 */
const COLLECTION: FakeExecution[] = Array.from({ length: 360 }, (_, i) => {
  const hoursAgo = i < 40 ? (i + 1) * 0.5 : i < 200 ? 25 + i : 200 + i * 2
  const status = i % 5 === 0 ? 'failed' : i % 17 === 0 ? 'cancelled' : 'completed'
  return makeExecution(i, hoursAgo, status)
})

const WITHIN_24H = COLLECTION.filter(
  (e) => e.started_at >= new Date(Date.now() - 24 * HOUR_MS).toISOString(),
).length
const COMPLETED_IN_24H = COLLECTION.filter(
  (e) =>
    e.status === 'completed' &&
    e.started_at >= new Date(Date.now() - 24 * HOUR_MS).toISOString(),
).length

function matchesSearch(row: FakeExecution, term: string): boolean {
  const needle = term.toLowerCase()
  return (
    row.workflow_execution_id.toLowerCase().includes(needle) ||
    row.workflow_id.toLowerCase().includes(needle) ||
    row.workflow_name.toLowerCase().includes(needle)
  )
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ExecutionList />
    </MemoryRouter>,
  )
}

function queriesSent(): ListQuery[] {
  return mockList.mock.calls.map(([query]) => query)
}

/**
 * The Workflow cell of every rendered row.
 *
 * Queried through the DOM rather than `getAllByRole('row')` because
 * ResourceTable puts `role="button"` on each `<tr>` for keyboard activation,
 * which displaces the implicit row role. Column 2 is Workflow: the selection
 * checkbox is 0 and Status is 1.
 */
function renderedWorkflowNames(): string[] {
  const rows = screen.getByRole('table').querySelectorAll('tbody tr')
  return Array.from(rows, (row) => row.querySelectorAll('td')[2]?.textContent ?? '')
}

describe('ExecutionList paging and filters', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockList.mockImplementation(async (query) => {
      const answer = answerListQuery(COLLECTION, query, matchesSearch)
      return {
        executions: answer.rows,
        total: answer.total,
        page: query.page,
        page_size: query.page_size,
        status_counts: answer.status_counts,
      }
    })
  })

  it('sends the time window to the server and re-renders on a wider one', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByText(`Showing 1-${WITHIN_24H} of ${WITHIN_24H} executions`)

    const first = queriesSent()[0]
    expect(first.started_after).toBeDefined()
    // The API rejects a bound with no offset (422), so it must carry one.
    expect(first.started_after).toMatch(/(Z|[+-]\d{2}:\d{2})$/)
    const narrowRows = renderedWorkflowNames()
    expect(narrowRows).toHaveLength(WITHIN_24H)

    await user.click(screen.getByRole('radio', { name: '7d' }))

    // A new request, carrying a bound that reaches further back than the last.
    await waitFor(() => expect(queriesSent().length).toBeGreaterThan(1))
    const widened = queriesSent().at(-1)!
    expect(widened.started_after).toBeDefined()
    expect(widened.started_after! < first.started_after!).toBe(true)

    // And the rows on screen actually changed.
    await waitFor(() => {
      expect(renderedWorkflowNames()).toHaveLength(50)
    })
    expect(renderedWorkflowNames()).not.toEqual(narrowRows)
  })

  it('reaches the oldest execution by paging, over more rows than one page', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('radio', { name: 'All' }))
    await screen.findByText('Showing 1-50 of 360 executions')

    const oldest = [...COLLECTION].sort((a, b) =>
      a.started_at.localeCompare(b.started_at),
    )[0]
    expect(screen.queryByText(oldest.workflow_name)).toBeNull()

    for (let hop = 0; hop < 7; hop += 1) {
      await user.click(screen.getByRole('button', { name: 'Next' }))
      await waitFor(() =>
        expect(screen.getByText(/^Page \d+ of 8$/).textContent).toBe(`Page ${hop + 2} of 8`),
      )
    }

    await screen.findByText('Showing 351-360 of 360 executions')
    expect(screen.getByText(oldest.workflow_name)).not.toBeNull()
    expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Next' }).disabled).toBe(true)

    await user.click(screen.getByRole('button', { name: 'Previous' }))
    await screen.findByText('Showing 301-350 of 360 executions')
    // Eight renders of a fifty-row table; slower than the 5s default allows.
  }, 30_000)

  it('labels the chips from the server facet counts, not the rows it holds', async () => {
    renderPage()

    await screen.findByText(`Showing 1-${WITHIN_24H} of ${WITHIN_24H} executions`)

    const chip = screen.getByRole('button', { name: /^Completed/ })
    expect(chip.textContent).toContain(String(COMPLETED_IN_24H))

    // Counting the held rows would agree here only by coincidence, so widen
    // until the true figure cannot fit on a page and check it again.
    const user = userEvent.setup()
    await user.click(screen.getByRole('radio', { name: 'All' }))
    await screen.findByText('Showing 1-50 of 360 executions')

    const completedInAll = COLLECTION.filter((e) => e.status === 'completed').length
    expect(completedInAll).toBeGreaterThan(50)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^Completed/ }).textContent).toContain(
        String(completedInAll),
      ),
    )
    // The page holds 50 rows; the chip must not be reporting those.
    expect(renderedWorkflowNames()).toHaveLength(50)
  })

  it('reports the server total in "showing N of M", not the page length', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('radio', { name: 'All' }))
    await screen.findByText('Showing 1-50 of 360 executions')

    expect(renderedWorkflowNames()).toHaveLength(50)
    expect(screen.queryByText('Showing 1-50 of 50 executions')).toBeNull()
  })

  it('narrows on the server when a status chip is selected, and returns to page 1', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('radio', { name: 'All' }))
    await screen.findByText('Showing 1-50 of 360 executions')

    await user.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('Showing 51-100 of 360 executions')

    await user.click(screen.getByRole('button', { name: /^Failed/ }))

    const failedInAll = COLLECTION.filter((e) => e.status === 'failed').length
    await waitFor(() => {
      const latest = queriesSent().at(-1)!
      expect(latest.statuses).toEqual(['failed'])
      expect(latest.page).toBe(1)
    })
    await screen.findByText(
      `Showing 1-${Math.min(50, failedInAll)} of ${failedInAll} executions`,
    )
  })

  it('sends the search term to the server rather than filtering the page', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('radio', { name: 'All' }))
    await screen.findByText('Showing 1-50 of 360 executions')

    await user.type(screen.getByPlaceholderText('Search executions...'), 'Run 359')

    await waitFor(() => expect(queriesSent().at(-1)!.q).toBe('Run 359'))
    // Run 359 is the oldest row and was on no page the browser held.
    await screen.findByText('Showing 1-1 of 1 execution')
    expect(screen.getByText('Run 359')).not.toBeNull()
  })
})
