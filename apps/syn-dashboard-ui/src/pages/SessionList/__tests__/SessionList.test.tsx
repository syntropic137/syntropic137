/**
 * Sessions page against a server that really filters and pages (#1159).
 *
 * The sessions endpoint took `limit` and the browser never sent `page`, so
 * every session past the first fifty was unreachable however the operator
 * filtered. What proves that fixed is the request the browser issues, not the
 * argument the hook passed to the function that builds one - so the double is
 * mounted over `fetch` and the query strings it receives are the subject.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { serveListEndpoint } from '../../../test/fakeListServer'
import { LIST_PAGE_SIZE } from '../../../hooks/useServerList'
import { SessionList } from '../SessionList'

vi.mock('../../../hooks/useActivityStream', () => ({
  useActivityStream: vi.fn(() => ({ connected: true, lastEventAt: null })),
}))

type User = ReturnType<typeof userEvent.setup>

const HOUR_MS = 60 * 60 * 1000
const DAY_MS = 24 * HOUR_MS

interface FakeSession {
  id: string
  status: string
  started_at: string
  workflow_id: string
  workflow_name: string
  total_tokens: number
}

/**
 * 120 sessions laid out like the executions fixture, and for the same reason:
 *   000-029   within the last 24h   (the default window)
 *   030-079   1-7 days old          (so 7d holds 80: more than one page)
 *   080-119   older than 7 days     (so All holds 120: also more than one page)
 *
 * Both windows overflow a page, which is the production shape. A fixture whose
 * narrow window fits on one page makes widening look like it changes the rows
 * on screen; against more than a page of matches it does not, and cannot.
 */
const COLLECTION: FakeSession[] = Array.from({ length: 120 }, (_, i) => {
  const hoursAgo = i < 30 ? (i + 1) * 0.5 : i < 80 ? 25 + (i - 30) * 2 : 200 + (i - 80) * 24
  return {
    id: `sess-${String(i).padStart(3, '0')}`,
    status: i % 4 === 0 ? 'failed' : 'completed',
    started_at: new Date(Date.now() - hoursAgo * HOUR_MS).toISOString(),
    workflow_id: 'wf-1',
    workflow_name: `Session ${String(i).padStart(3, '0')}`,
    total_tokens: 100,
  }
})

const TOTAL = COLLECTION.length
const WITHIN_7D = COLLECTION.filter(
  (s) => s.started_at >= new Date(Date.now() - 7 * DAY_MS).toISOString(),
).length
/** The oldest session: reachable only under "All", and only past page one. */
const OLDEST = COLLECTION[TOTAL - 1]

const server = serveListEndpoint({
  path: '/api/v1/sessions',
  collection: COLLECTION,
  matchesSearch: (row, term) => row.id.toLowerCase().includes(term.toLowerCase()),
})

function renderPage(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <SessionList />
    </MemoryRouter>,
  )
}

/**
 * The Workflow cell of every rendered row. Queried through the DOM because
 * ResourceTable puts `role="button"` on each `<tr>`, displacing the implicit
 * row role. Column 2 is Workflow: the selection checkbox is 0 and Status is 1.
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

describe('SessionList paging', () => {
  it('asks the server for a page, and page 2 holds different sessions', async () => {
    const user = userEvent.setup()
    renderPage('/sessions?timeWindow=all')

    await screen.findByText(`Showing 1-${LIST_PAGE_SIZE} of ${TOTAL} sessions`)

    const { params } = server.requests[0]
    expect(params.get('page')).toBe('1')
    expect(params.get('page_size')).toBe(String(LIST_PAGE_SIZE))
    // The deprecated alias is gone; nothing sends `limit` any more.
    expect(params.has('limit')).toBe(false)

    const firstPage = renderedWorkflowNames()
    expect(firstPage).toHaveLength(LIST_PAGE_SIZE)

    await user.click(screen.getByRole('button', { name: 'Next' }))

    await screen.findByText(`Showing 51-100 of ${TOTAL} sessions`)
    // The page number reached the query string, not merely the hook.
    expect(server.lastRequest.params.get('page')).toBe('2')

    const secondPage = renderedWorkflowNames()
    expect(secondPage).toHaveLength(LIST_PAGE_SIZE)
    expect(secondPage).not.toEqual(firstPage)
    // Not merely reordered - no session appears on both pages.
    expect(secondPage.filter((name) => firstPage.includes(name))).toEqual([])
  }, 30_000)

  it('widening the window to All raises the total and reaches history no 7d page held', async () => {
    const user = userEvent.setup()

    // The case only bites when both windows overflow a page; assert the
    // fixture is that shape rather than trusting it to stay that way.
    expect(WITHIN_7D).toBeGreaterThan(LIST_PAGE_SIZE)
    expect(TOTAL).toBeGreaterThan(WITHIN_7D)
    expect(OLDEST.started_at < new Date(Date.now() - 7 * DAY_MS).toISOString()).toBe(true)

    renderPage('/sessions?timeWindow=7d')
    await screen.findByText(`Showing 1-${LIST_PAGE_SIZE} of ${WITHIN_7D} sessions`)
    const firstPageUnder7d = renderedWorkflowNames()

    // Page to the end of the 7d window: the oldest session is not in it.
    await pageToLast(user, WITHIN_7D)
    await screen.findByText(`Showing 51-${WITHIN_7D} of ${WITHIN_7D} sessions`)
    expect(screen.queryByText(OLDEST.workflow_name)).toBeNull()

    await user.click(screen.getByRole('radio', { name: 'All' }))

    // The total changes, and the affordance reports the new one.
    await screen.findByText(`Showing 1-${LIST_PAGE_SIZE} of ${TOTAL} sessions`)
    // The rows do NOT change, and must not be expected to: these are the
    // newest 50 either way. "More rows are visible after widening" is the
    // intuitive criterion and it is wrong - it would fail correct software.
    expect(renderedWorkflowNames()).toEqual(firstPageUnder7d)

    // What widening actually buys is reach, so page all the way in.
    await pageToLast(user, TOTAL)
    await screen.findByText(`Showing 101-${TOTAL} of ${TOTAL} sessions`)
    expect(screen.getByText(OLDEST.workflow_name)).not.toBeNull()

    // And that reach is on the wire: the last page, with the bound dropped.
    expect(server.lastRequest.params.get('page')).toBe('3')
    expect(server.lastRequest.params.has('started_after')).toBe(false)
  }, 30_000)

  it('reports the server total, not the number of rows it is holding', async () => {
    renderPage('/sessions?timeWindow=all')

    await screen.findByText(`Showing 1-${LIST_PAGE_SIZE} of ${TOTAL} sessions`)
    expect(renderedWorkflowNames()).toHaveLength(LIST_PAGE_SIZE)
    expect(screen.queryByText(`Showing 1-50 of ${LIST_PAGE_SIZE} sessions`)).toBeNull()
  })

  it('puts the time window on the request as a bound the API will accept', async () => {
    renderPage('/sessions')

    await waitFor(() => expect(server.requests.length).toBeGreaterThan(0))
    // A bound with no offset is a 422 from the API.
    expect(server.requests[0].params.get('started_after')).toMatch(/(Z|[+-]\d{2}:\d{2})$/)
  })
})
