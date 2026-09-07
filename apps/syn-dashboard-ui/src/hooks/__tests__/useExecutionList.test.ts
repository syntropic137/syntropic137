/**
 * The executions list, against a server that really filters, tallies and pages.
 *
 * #1159 lived in this hook: it fetched one unfiltered page of 50 and narrowed
 * it in the browser, so the row count, the status chips and the time window
 * all described the newest 50 executions rather than the collection. With ~360
 * executions "235 completed" rendered as 35, and the oldest row could not be
 * reached by any interaction.
 *
 * Every assertion below therefore rests on the fixture being BIGGER THAN ONE
 * PAGE (120 rows, three pages). At 50 rows or fewer none of them can fail:
 * `total` and `rows.length` agree, and page 2 is empty whether or not paging
 * works. See `src/test/listFixtures.ts`.
 *
 * The double is mounted over `fetch` rather than over the api module, so the
 * request this hook really issued is the subject - a filter that never reaches
 * the query string is exactly the bug, and mocking `listAllExecutions` would
 * leave `listQueryParams` unexecuted.
 */

import { describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'

import { serveListEndpoint } from '../../test/fakeListServer'
import { DAY_MS, EXECUTIONS, matchesExecutionSearch, tally, within } from '../../test/listFixtures'
import { LIST_PAGE_SIZE } from '../useServerList'
import { useExecutionList } from '../useExecutionList'

vi.mock('../useActivityStream', () => ({
  useActivityStream: vi.fn(() => ({ connected: true, lastEventAt: null })),
}))

const server = serveListEndpoint({
  path: '/api/v1/executions',
  collection: EXECUTIONS,
  matchesSearch: matchesExecutionSearch,
})

const TOTAL = EXECUTIONS.length
const startedAt = (row: { started_at: string }) => row.started_at
const IN_7D = within(EXECUTIONS, 7 * DAY_MS, startedAt).length
const STATUS_COUNTS = tally(EXECUTIONS, (row) => row.status)
const COMPLETED = STATUS_COUNTS.completed

function wrapperAt(url: string) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(MemoryRouter, { initialEntries: [url] }, children)
  }
}

/** The ids the server should have put on page `page` of the whole collection. */
function idsOnPage(page: number): string[] {
  const offset = (page - 1) * LIST_PAGE_SIZE
  return EXECUTIONS.slice(offset, offset + LIST_PAGE_SIZE).map((e) => e.workflow_execution_id)
}

/** Render over the unbounded window, where the collection is all 120 rows. */
function renderList(url = '/executions?timeWindow=all') {
  const rendered = renderHook(() => useExecutionList(), { wrapper: wrapperAt(url) })
  const ids = () => rendered.result.current.executions.map((e) => e.workflow_execution_id)
  return { ...rendered, ids }
}

describe('useExecutionList', () => {
  it('is the fixture the regression needs: more than one page, in both windows', () => {
    // Asserted rather than assumed. Every test in this file is vacuous if the
    // collection ever shrinks to a page, and it would still be green.
    expect(TOTAL).toBeGreaterThan(LIST_PAGE_SIZE * 2)
    expect(IN_7D).toBeGreaterThan(LIST_PAGE_SIZE)
    expect(TOTAL).toBeGreaterThan(IN_7D)
    expect(COMPLETED).toBeGreaterThan(LIST_PAGE_SIZE)
  })

  it('reports the collection total, not the number of rows on the page', async () => {
    const { result, ids } = renderList()

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.total).toBe(TOTAL)
    expect(result.current.executions).toHaveLength(LIST_PAGE_SIZE)
    // The two numbers must not be the same one. This is #1159 exactly.
    expect(result.current.total).not.toBe(result.current.executions.length)
    expect(result.current.pageSize).toBe(LIST_PAGE_SIZE)
    expect(result.current.totalPages).toBe(3)
    expect(ids()).toEqual(idsOnPage(1))
  })

  it('holds the total steady while paging, as the rows beneath it change', async () => {
    const { result, ids } = renderList()
    await waitFor(() => expect(result.current.loading).toBe(false))

    const seenTotals = [result.current.total]
    const seenRowCounts = [result.current.executions.length]

    for (const page of [2, 3]) {
      act(() => result.current.setPage(page))
      await waitFor(() => expect(ids()).toEqual(idsOnPage(page)))
      seenTotals.push(result.current.total)
      seenRowCounts.push(result.current.executions.length)
    }

    // `page_size` is not a parameter this hook exposes - `useListQuery`
    // hardcodes `LIST_PAGE_SIZE` - so the page size cannot be varied from
    // here. Varying the PAGE is the same property from the same fixture: a
    // total computed from the rows in hand would have read 50, 50, 20.
    expect(seenTotals).toEqual([TOTAL, TOTAL, TOTAL])
    expect(seenRowCounts).toEqual([LIST_PAGE_SIZE, LIST_PAGE_SIZE, TOTAL - 2 * LIST_PAGE_SIZE])
  })

  it('page 2 holds different executions, and is not empty', async () => {
    const { result, ids } = renderList()
    await waitFor(() => expect(result.current.loading).toBe(false))
    const firstPage = ids()

    act(() => result.current.setPage(2))
    await waitFor(() => expect(server.lastRequest.params.get('page')).toBe('2'))
    await waitFor(() => expect(ids()).toEqual(idsOnPage(2)))

    expect(ids()).toHaveLength(LIST_PAGE_SIZE)
    expect(ids()).not.toEqual(firstPage)
    expect(firstPage.some((id) => ids().includes(id))).toBe(false)
  })

  it('paging reaches the last page, and the arithmetic closes on the total', async () => {
    const { result, ids } = renderList()
    await waitFor(() => expect(result.current.loading).toBe(false))

    for (const page of [2, 3]) {
      act(() => result.current.setPage(page))
      await waitFor(() => expect(ids()).toEqual(idsOnPage(page)))
    }

    const lastPageRows = result.current.executions.length
    expect(result.current.page).toBe(3)
    expect((result.current.totalPages - 1) * result.current.pageSize + lastPageRows).toBe(TOTAL)
    // The oldest execution exists and is reachable, which under #1159 it was not.
    expect(ids()).toContain(EXECUTIONS[TOTAL - 1].workflow_execution_id)
  })

  it('widening the time window changes the total, though page 1 may not move', async () => {
    const { result, ids } = renderList('/executions?timeWindow=7d')
    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.total).toBe(IN_7D)
    const firstPageUnder7d = ids()

    act(() => result.current.setTimeWindow('all'))
    await waitFor(() => expect(result.current.total).toBe(TOTAL))

    // Deliberately NOT an assertion that the rows changed. Both windows hold
    // more than a page, and widening a lower bound on a newest-first list
    // cannot change the newest 50 - so "more rows are visible now" is the
    // intuitive criterion and it would fail correct software.
    expect(ids()).toEqual(firstPageUnder7d)
    // What widening buys is reach, and it is on the wire: the bound is gone.
    expect(server.lastRequest.params.has('started_after')).toBe(false)
  })

  it('narrowing the window also changes the total', async () => {
    const { result } = renderList()
    await waitFor(() => expect(result.current.total).toBe(TOTAL))

    act(() => result.current.setTimeWindow('24h'))

    const IN_24H = within(EXECUTIONS, DAY_MS, startedAt).length
    await waitFor(() => expect(result.current.total).toBe(IN_24H))
    expect(IN_24H).toBeLessThan(TOTAL)
  })

  it('takes the status counts from the server, over the collection', async () => {
    const { result } = renderList()
    await waitFor(() => expect(result.current.loading).toBe(false))

    // Counted over 120 rows while 50 are in hand: a client-side tally of the
    // page could not produce this number at all.
    expect(result.current.statusCounts).toEqual(STATUS_COUNTS)
    expect(result.current.statusCounts.completed).toBeGreaterThan(LIST_PAGE_SIZE)
  })

  it('keeps reporting every status once one of them is selected', async () => {
    const { result } = renderList()
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => result.current.toggleStatus('completed'))
    await waitFor(() => expect(result.current.total).toBe(COMPLETED))

    expect(server.lastRequest.params.get('statuses')).toBe('completed')
    expect(result.current.page).toBe(1)
    // Selecting a chip narrows the rows, not the tally: an unselected chip
    // still reports what selecting it would get.
    expect(result.current.statusCounts).toEqual(STATUS_COUNTS)
    expect(result.current.statusCounts.failed).toBe(STATUS_COUNTS.failed)
  })

  it('sends the search term to the server rather than narrowing the page', async () => {
    const { result } = renderList()
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => result.current.setSearchQuery('Run 119'))

    // Row 119 is the oldest execution, three pages from the one in hand, so it
    // could only ever be found by asking the server for it.
    await waitFor(() => expect(server.lastRequest.params.get('q')).toBe('Run 119'))
    await waitFor(() => expect(result.current.total).toBe(1))
    expect(result.current.executions.map((e) => e.workflow_execution_id)).toEqual([
      EXECUTIONS[TOTAL - 1].workflow_execution_id,
    ])
  })
})
