/**
 * A queued start is a row on the Executions list, saying where it waits and
 * why (PC-124).
 *
 * The server sends `start_queue` on the row; the hook maps every list row into
 * a hand-written `ExecutionListItem`, which is exactly the hop where a field
 * the server sent is silently dropped. So this renders the page over `fetch`
 * and reads the row, rather than checking the mapped object.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { serveListEndpoint } from '../../../test/fakeListServer'
import { EXECUTIONS, matchesExecutionSearch } from '../../../test/listFixtures'
import { ExecutionList } from '../ExecutionList'

vi.mock('../../../hooks/useActivityStream', () => ({
  useActivityStream: vi.fn(() => ({ connected: true, lastEventAt: null })),
}))

const QUEUED_RUN = {
  ...EXECUTIONS[0],
  workflow_execution_id: 'exec-queued',
  workflow_name: 'Waiting run',
  status: 'queued',
  start_queue: {
    path: 'direct' as const,
    position: 2,
    held: true,
    running: 4,
    waiting: 3,
    limit: 4,
    queued_at: EXECUTIONS[0].started_at,
    position_display: 'queued 2 of 3 (4/4 running)',
    reason_display: 'slots full 4/4',
  },
}

serveListEndpoint({
  path: '/api/v1/executions',
  collection: [QUEUED_RUN, EXECUTIONS[1]],
  matchesSearch: matchesExecutionSearch,
})

describe('a queued execution on the Executions list', () => {
  it('shows its place in the queue and why it waits', async () => {
    render(
      <MemoryRouter initialEntries={['/executions']}>
        <ExecutionList />
      </MemoryRouter>,
    )

    await screen.findByText('Waiting run')
    const rows = Array.from(screen.getByRole('table').querySelectorAll('tbody tr'))
    const row = rows.find((r) => r.textContent?.includes('Waiting run'))
    expect(row?.textContent).toContain('queued 2 of 3 (4/4 running): slots full 4/4')
  })

  it('offers a Queued chip counted by the server', async () => {
    render(
      <MemoryRouter initialEntries={['/executions']}>
        <ExecutionList />
      </MemoryRouter>,
    )

    const chip = await screen.findByRole('button', { name: /^Queued/ })
    expect(chip.textContent).toContain('1')
  })
})
