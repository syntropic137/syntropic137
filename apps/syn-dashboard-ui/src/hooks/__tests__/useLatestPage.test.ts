/**
 * The answer to the most recent query, and only that one.
 *
 * Two separate contracts, tested two ways because they fail differently.
 *
 * The sequencing one - a response that has been overtaken is discarded - is
 * about the order two promises settle in, so it is driven by promises this
 * file resolves by hand. A real endpoint would settle them in whatever order
 * it liked, which is not a test.
 *
 * The counting one - `total` is the server's number, not the length of what
 * arrived - is the #1159/#1204 defect itself, and it lives in the hop between
 * the wire and the hook. So that one runs against the real `/api/v1/executions`
 * client over a 120-row endpoint, where `listQueryParams` and the response
 * envelope actually execute.
 *
 * This is also the only hook of the three whose page size a caller chooses:
 * `useListQuery` hardcodes `LIST_PAGE_SIZE`, so "the same total at every page
 * size" is expressible here and nowhere above it.
 */

import { describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'

import { listAllExecutions } from '../../api/executions'
import type { ListPage, ListQuery } from '../../api/listQuery'
import { serveListEndpoint } from '../../test/fakeListServer'
import { EXECUTIONS, matchesExecutionSearch } from '../../test/listFixtures'
import type { ExecutionListResponse } from '../../types'
import { LIST_PAGE_SIZE } from '../useListQuery'
import { useLatestPage } from '../useLatestPage'

serveListEndpoint({
  path: '/api/v1/executions',
  collection: EXECUTIONS,
  matchesSearch: matchesExecutionSearch,
})

type ExecutionRow = ExecutionListResponse['executions'][number]

/** The real client, so the query string and the envelope are both exercised. */
async function fetchExecutionPage(query: ListQuery): Promise<ListPage<ExecutionRow>> {
  const response = await listAllExecutions(query)
  return {
    rows: response.executions,
    total: response.total,
    statusCounts: response.status_counts ?? {},
  }
}

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (error: unknown) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function page(rows: string[], total: number): ListPage<{ id: string }> {
  return { rows: rows.map((id) => ({ id })), total, statusCounts: {} }
}

/** Every `ListQuery` here is built once, outside render: identity is a refetch. */
const FIRST_PAGE: ListQuery = { page: 1, page_size: LIST_PAGE_SIZE }

describe('useLatestPage', () => {
  it('is empty and loading until the first page lands', async () => {
    const pending = deferred<ListPage<{ id: string }>>()
    const fetchPage = vi.fn(() => pending.promise)

    const { result } = renderHook(() => useLatestPage(fetchPage, FIRST_PAGE))

    expect(result.current.loading).toBe(true)
    expect(result.current.result).toEqual({
      rows: [],
      total: 0,
      statusCounts: {},
      excludedUndated: 0,
    })

    pending.resolve(page(['a'], 1))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.result.rows).toEqual([{ id: 'a' }])
  })

  it('carries the total the fetch reported, not the number of rows it returned', async () => {
    const rows = EXECUTIONS.slice(0, LIST_PAGE_SIZE).map((e) => e.workflow_execution_id)
    const fetchPage = vi.fn(async () => page(rows, EXECUTIONS.length))

    const { result } = renderHook(() => useLatestPage(fetchPage, FIRST_PAGE))

    await waitFor(() => expect(result.current.loading).toBe(false))
    // The page is 50 rows; the collection is 120. A hook that reported what it
    // was holding would say 50, and every count downstream would be a page.
    expect(result.current.result.rows).toHaveLength(LIST_PAGE_SIZE)
    expect(result.current.result.total).toBe(EXECUTIONS.length)
    expect(result.current.result.total).not.toBe(result.current.result.rows.length)
  })

  it('reports the same total at every page size, while the row counts differ', async () => {
    const observed: { pageSize: number; total: number; rows: number }[] = []

    for (const pageSize of [1, 10, LIST_PAGE_SIZE]) {
      const query: ListQuery = { page: 1, page_size: pageSize }
      const { result, unmount } = renderHook(() => useLatestPage(fetchExecutionPage, query))

      await waitFor(() => expect(result.current.loading).toBe(false))
      observed.push({
        pageSize,
        total: result.current.result.total,
        rows: result.current.result.rows.length,
      })
      unmount()
    }

    // This is the property that tells a real count from a page length: change
    // how much you ask for and the answer to "how many are there" must not
    // move. `rows.length` would have tracked the page size exactly.
    expect(observed.map((o) => o.total)).toEqual([120, 120, 120])
    expect(observed.map((o) => o.rows)).toEqual([1, 10, LIST_PAGE_SIZE])
  })

  it('reaches the last page, and the arithmetic closes on the total', async () => {
    const pageSize = LIST_PAGE_SIZE
    const total = EXECUTIONS.length
    const lastPage = Math.ceil(total / pageSize)
    const query: ListQuery = { page: lastPage, page_size: pageSize }

    const { result } = renderHook(() => useLatestPage(fetchExecutionPage, query))

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(lastPage).toBe(3)
    expect(result.current.result.total).toBe(total)
    expect((lastPage - 1) * pageSize + result.current.result.rows.length).toBe(total)
  })

  it('discards a response that was overtaken by a later query', async () => {
    const first = deferred<ListPage<{ id: string }>>()
    const second = deferred<ListPage<{ id: string }>>()
    const responses = [first, second]
    const fetchPage = vi.fn(() => responses.shift()!.promise)

    const pageTwo: ListQuery = { page: 2, page_size: LIST_PAGE_SIZE }
    const { result, rerender } = renderHook(({ query }) => useLatestPage(fetchPage, query), {
      initialProps: { query: FIRST_PAGE },
    })

    rerender({ query: pageTwo })
    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(2))

    second.resolve(page(['page-2-row'], 120))
    await waitFor(() => expect(result.current.result.rows).toEqual([{ id: 'page-2-row' }]))

    // Page 1's answer arrives late. Rendering it would put another page's rows
    // under the current page's controls.
    //
    // Resolved inside `act`, which returns only once React has run what
    // settling that promise scheduled AND committed the result. Awaiting a
    // microtask instead asserts before a `setResult` could have reached the
    // screen, so it passes whether or not the response was discarded - the
    // same shape of check-that-cannot-fail as the count this file exists to
    // pin. Its rows AND its total differ from page 2's, so neither assertion
    // below can be satisfied by the wrong response.
    await act(async () => {
      first.resolve(page(['page-1-row'], 999))
    })

    expect(result.current.result.rows).toEqual([{ id: 'page-2-row' }])
    expect(result.current.result.total).toBe(120)
  })

  it('refetches when the query changes identity', async () => {
    const fetchPage = vi.fn(async () => page(['a'], 1))
    const pageTwo: ListQuery = { page: 2, page_size: LIST_PAGE_SIZE }

    const { rerender } = renderHook(({ query }) => useLatestPage(fetchPage, query), {
      initialProps: { query: FIRST_PAGE },
    })

    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(1))
    rerender({ query: pageTwo })

    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(2))
    expect(fetchPage.mock.calls.at(-1)?.[0]).toBe(pageTwo)
  })

  it('holds refetch stable while the query is unchanged', async () => {
    const fetchPage = vi.fn(async () => page(['a'], 1))

    const { result, rerender } = renderHook(() => useLatestPage(fetchPage, FIRST_PAGE))

    await waitFor(() => expect(result.current.loading).toBe(false))
    const refetch = result.current.refetch
    rerender()

    // Callers pass it to `useLiveRefresh`, which restarts its poll whenever it
    // changes: a fresh one per render would reset the interval forever.
    expect(result.current.refetch).toBe(refetch)
  })

  it('asks again for the same query when refetched', async () => {
    const pages = [page(['a'], 1), page(['b'], 1)]
    const fetchPage = vi.fn(async () => pages.shift()!)

    const { result } = renderHook(() => useLatestPage(fetchPage, FIRST_PAGE))

    await waitFor(() => expect(result.current.result.rows).toEqual([{ id: 'a' }]))
    result.current.refetch()

    await waitFor(() => expect(result.current.result.rows).toEqual([{ id: 'b' }]))
    expect(fetchPage.mock.calls.at(-1)?.[0]).toBe(FIRST_PAGE)
  })

  it('leaves the last good page on screen when a request fails', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      const outcomes: (() => Promise<ListPage<{ id: string }>>)[] = [
        async () => page(['a'], 1),
        async () => {
          throw new Error('Network error')
        },
      ]
      const fetchPage = vi.fn(() => outcomes.shift()!())

      const { result } = renderHook(() => useLatestPage(fetchPage, FIRST_PAGE))
      await waitFor(() => expect(result.current.result.rows).toEqual([{ id: 'a' }]))

      result.current.refetch()

      await waitFor(() => expect(consoleError).toHaveBeenCalled())
      expect(result.current.result.rows).toEqual([{ id: 'a' }])
      expect(result.current.loading).toBe(false)
    } finally {
      consoleError.mockRestore()
    }
  })
})
