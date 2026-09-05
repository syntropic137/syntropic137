/**
 * Executions page against a server that really filters and pages (#1159).
 *
 * These assertions are all about the page an operator sees and the request the
 * browser issued to get it, not about the hook's return value, because every
 * one of the bugs they cover was a value that existed correctly one hop
 * earlier: the server sent `total` and `status_counts` and the browser
 * rendered `rows.length`; the hook held a page number that never reached a
 * query string. So the double here is mounted over `fetch` and the requests it
 * receives are the subject.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { serveListEndpoint } from '../../../test/fakeListServer'
import { EXECUTIONS, matchesExecutionSearch, within } from '../../../test/listFixtures'
import { LIST_PAGE_SIZE } from '../../../hooks/useServerList'
import { ExecutionList } from '../ExecutionList'

vi.mock('../../../hooks/useActivityStream', () => ({
  useActivityStream: vi.fn(() => ({ connected: true, lastEventAt: null })),
}))

type User = ReturnType<typeof userEvent.setup>

const DAY_MS = 24 * 60 * 60 * 1000

/**
 * The same 120-row, three-page collection the hook tests use.
 *
 * Shared rather than restated: this shape - both windows overflowing a page -
 * is the only reason any of these assertions can fail, and a second copy of it
 * is a second chance to quietly shrink it back under one page.
 */
const COLLECTION = EXECUTIONS
const TOTAL = COLLECTION.length
const startedAt = (row: { started_at: string }) => row.started_at
const within24h = () => within(COLLECTION, DAY_MS, startedAt)
const WITHIN_24H = within24h().length
const WITHIN_7D = within(COLLECTION, 7 * DAY_MS, startedAt).length
const COMPLETED_IN_24H = within24h().filter((e) => e.status === 'completed').length
/** The oldest row: reachable only under "All", and only past the first page. */
const OLDEST = COLLECTION[TOTAL - 1]

const server = serveListEndpoint({
  path: '/api/v1/executions',
  collection: COLLECTION,
  matchesSearch: matchesExecutionSearch,
})

function renderPage(url = '/executions') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <ExecutionList />
    </MemoryRouter>,
  )
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

/** Walk to the last page of `total` rows, one Next at a time. */
async function pageToLast(user: User, total: number): Promise<void> {
  const lastPage = Math.ceil(total / LIST_PAGE_SIZE)
  for (let page = 2; page <= lastPage; page += 1) {
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText(`Page ${page} of ${lastPage}`)
  }
}

describe('ExecutionList paging and filters', () => {
  it('puts the time window on the request as a bound the API will accept', async () => {
    renderPage()

    await screen.findByText(`Showing 1-${WITHIN_24H} of ${WITHIN_24H} executions`)

    const { params } = server.requests[0]
    expect(params.get('page')).toBe('1')
    expect(params.get('page_size')).toBe(String(LIST_PAGE_SIZE))
    // The API rejects a bound with no offset (422), so it must carry one.
    expect(params.get('started_after')).toMatch(/(Z|[+-]\d{2}:\d{2})$/)
    expect(renderedWorkflowNames()).toHaveLength(WITHIN_24H)
  })

  it('widening the window to All raises the total and reaches history no 7d page held', async () => {
    const user = userEvent.setup()

    // The case only bites when both windows overflow a page; assert the
    // fixture is that shape rather than trusting it to stay that way.
    expect(WITHIN_7D).toBeGreaterThan(LIST_PAGE_SIZE)
    expect(TOTAL).toBeGreaterThan(WITHIN_7D)
    expect(OLDEST.started_at < new Date(Date.now() - 7 * DAY_MS).toISOString()).toBe(true)

    renderPage('/executions?timeWindow=7d')
    await screen.findByText(`Showing 1-${LIST_PAGE_SIZE} of ${WITHIN_7D} executions`)
    const firstPageUnder7d = renderedWorkflowNames()

    // Page to the end of the 7d window: its oldest row is still inside it.
    await pageToLast(user, WITHIN_7D)
    await screen.findByText(`Showing 51-${WITHIN_7D} of ${WITHIN_7D} executions`)
    expect(screen.queryByText(OLDEST.workflow_name)).toBeNull()

    await user.click(screen.getByRole('radio', { name: 'All' }))

    // The total changes, and the affordance reports the new one.
    await screen.findByText(`Showing 1-${LIST_PAGE_SIZE} of ${TOTAL} executions`)
    // The rows do NOT change, and must not be expected to: these are the
    // newest 50 either way. "More rows are visible after widening" is the
    // intuitive criterion and it is wrong - it would fail correct software.
    expect(renderedWorkflowNames()).toEqual(firstPageUnder7d)

    // What widening actually buys is reach, so page all the way in.
    await pageToLast(user, TOTAL)
    await screen.findByText(`Showing 101-${TOTAL} of ${TOTAL} executions`)
    expect(screen.getByText(OLDEST.workflow_name)).not.toBeNull()

    // And that reach is on the wire: the last page, with the bound dropped.
    expect(server.lastRequest.params.get('page')).toBe('3')
    expect(server.lastRequest.params.has('started_after')).toBe(false)
  }, 30_000)

  it('reaches the oldest execution by paging, over more rows than one page', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('radio', { name: 'All' }))
    await screen.findByText(`Showing 1-${LIST_PAGE_SIZE} of ${TOTAL} executions`)
    expect(screen.queryByText(OLDEST.workflow_name)).toBeNull()

    await pageToLast(user, TOTAL)

    await screen.findByText(`Showing 101-${TOTAL} of ${TOTAL} executions`)
    expect(screen.getByText(OLDEST.workflow_name)).not.toBeNull()
    expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Next' }).disabled).toBe(true)

    await user.click(screen.getByRole('button', { name: 'Previous' }))
    await screen.findByText(`Showing 51-100 of ${TOTAL} executions`)
    expect(server.lastRequest.params.get('page')).toBe('2')
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
    await screen.findByText(`Showing 1-${LIST_PAGE_SIZE} of ${TOTAL} executions`)

    const completedInAll = COLLECTION.filter((e) => e.status === 'completed').length
    expect(completedInAll).toBeGreaterThan(LIST_PAGE_SIZE)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^Completed/ }).textContent).toContain(
        String(completedInAll),
      ),
    )
    // The page holds 50 rows; the chip must not be reporting those.
    expect(renderedWorkflowNames()).toHaveLength(LIST_PAGE_SIZE)
  })

  it('reports the server total in "showing N of M", not the page length', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('radio', { name: 'All' }))
    await screen.findByText(`Showing 1-${LIST_PAGE_SIZE} of ${TOTAL} executions`)

    expect(renderedWorkflowNames()).toHaveLength(LIST_PAGE_SIZE)
    expect(screen.queryByText(`Showing 1-50 of ${LIST_PAGE_SIZE} executions`)).toBeNull()
  })

  it('narrows on the server when a status chip is selected, and returns to page 1', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('radio', { name: 'All' }))
    await screen.findByText(`Showing 1-${LIST_PAGE_SIZE} of ${TOTAL} executions`)

    await user.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText(`Showing 51-100 of ${TOTAL} executions`)
    expect(server.lastRequest.params.get('page')).toBe('2')

    await user.click(screen.getByRole('button', { name: /^Failed/ }))

    const failedInAll = COLLECTION.filter((e) => e.status === 'failed').length
    await waitFor(() => {
      const { params } = server.lastRequest
      expect(params.get('statuses')).toBe('failed')
      expect(params.get('page')).toBe('1')
    })
    await screen.findByText(
      `Showing 1-${Math.min(LIST_PAGE_SIZE, failedInAll)} of ${failedInAll} executions`,
    )
  })

  it('sends the search term to the server rather than filtering the page', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('radio', { name: 'All' }))
    await screen.findByText(`Showing 1-${LIST_PAGE_SIZE} of ${TOTAL} executions`)

    await user.type(screen.getByPlaceholderText('Search executions...'), OLDEST.workflow_name)

    await waitFor(() => expect(server.lastRequest.params.get('q')).toBe(OLDEST.workflow_name))
    // The oldest row was on no page the browser held.
    await screen.findByText('Showing 1-1 of 1 execution')
    expect(screen.getByText(OLDEST.workflow_name)).not.toBeNull()
  })
})
