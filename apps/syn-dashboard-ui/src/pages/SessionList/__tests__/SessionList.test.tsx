/**
 * Sessions page against a server that really pages (#1159).
 *
 * The sessions endpoint took `limit` and the browser never sent `page`, so
 * every session past the first fifty was unreachable however the operator
 * filtered. These assertions are about the second page existing and holding
 * different rows, which is the whole of what was missing.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { answerListQuery } from '../../../test/fakeListServer'
import type { ListQuery } from '../../../api/listQuery'
import { SessionList } from '../SessionList'

vi.mock('../../../api/sessions', () => ({ listSessions: vi.fn() }))
vi.mock('../../../hooks/useActivityStream', () => ({
  useActivityStream: vi.fn(() => ({ connected: true, lastEventAt: null })),
}))

import { listSessions } from '../../../api/sessions'

const mockList = vi.mocked(listSessions)

const HOUR_MS = 60 * 60 * 1000

interface FakeSession {
  id: string
  status: string
  started_at: string
  workflow_id: string
  workflow_name: string
  total_tokens: number
}

/** 120 sessions, all inside the default 24h window, so paging is the variable. */
const COLLECTION: FakeSession[] = Array.from({ length: 120 }, (_, i) => ({
  id: `sess-${String(i).padStart(3, '0')}`,
  status: i % 4 === 0 ? 'failed' : 'completed',
  started_at: new Date(Date.now() - (i + 1) * 0.1 * HOUR_MS).toISOString(),
  workflow_id: 'wf-1',
  workflow_name: `Session ${String(i).padStart(3, '0')}`,
  total_tokens: 100,
}))

function queriesSent(): ListQuery[] {
  return mockList.mock.calls.map(([query]) => query)
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

describe('SessionList paging', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockList.mockImplementation(async (query) => {
      const answer = answerListQuery(COLLECTION, query, (row, term) =>
        row.id.toLowerCase().includes(term.toLowerCase()),
      )
      return {
        sessions: answer.rows,
        total: answer.total,
        page: query.page,
        page_size: query.page_size,
        status_counts: answer.status_counts,
      }
    })
  })

  it('asks the server for a page, and page 2 holds different sessions', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <SessionList />
      </MemoryRouter>,
    )

    await screen.findByText('Showing 1-50 of 120 sessions')

    const first = queriesSent()[0]
    expect(first.page).toBe(1)
    expect(first.page_size).toBe(50)
    // The deprecated alias is gone; nothing sends `limit` any more.
    expect(first).not.toHaveProperty('limit')

    const firstPage = renderedWorkflowNames()
    expect(firstPage).toHaveLength(50)

    await user.click(screen.getByRole('button', { name: 'Next' }))

    await waitFor(() => expect(queriesSent().at(-1)!.page).toBe(2))
    await screen.findByText('Showing 51-100 of 120 sessions')

    const secondPage = renderedWorkflowNames()
    expect(secondPage).toHaveLength(50)
    expect(secondPage).not.toEqual(firstPage)
    // Not merely reordered - no session appears on both pages.
    expect(secondPage.filter((name) => firstPage.includes(name))).toEqual([])
  }, 30_000)

  it('reports the server total, not the number of rows it is holding', async () => {
    render(
      <MemoryRouter>
        <SessionList />
      </MemoryRouter>,
    )

    await screen.findByText('Showing 1-50 of 120 sessions')
    expect(renderedWorkflowNames()).toHaveLength(50)
    expect(screen.queryByText('Showing 1-50 of 50 sessions')).toBeNull()
  })
})
