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
 * client over a 240-row endpoint, where `listQueryParams` and the response
 * envelope actually execute.
 *
 * This is also the only hook of the three whose page size a caller chooses:
 * `useListQuery` hardcodes `LIST_PAGE_SIZE`, so "the same total at every page
 * size" is expressible here and nowhere above it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'

import { listAllExecutions } from '../../api/executions'
import type { ListPage, ListQuery } from '../../api/listQuery'
import { serveListEndpoint } from '../../test/fakeListServer'
import { EXECUTIONS, matchesExecutionSearch } from '../../test/listFixtures'
import type { ExecutionListResponse } from '../../types'
import { EXECUTION_LIST_PAGE_SIZE, LIST_PAGE_SIZE } from '../useListQuery'
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
    // The page is 50 rows; the collection is 240. A hook that reported what it
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
    expect(observed.map((o) => o.total)).toEqual([EXECUTIONS.length, EXECUTIONS.length, EXECUTIONS.length])
    expect(observed.map((o) => o.rows)).toEqual([1, 10, LIST_PAGE_SIZE])
  })

  it('reaches the last page, and the arithmetic closes on the total', async () => {
    // The executions fixture is three pages at the size its surface asks for.
    const pageSize = EXECUTION_LIST_PAGE_SIZE
    const total = EXECUTIONS.length
    const lastPage = Math.ceil(total / pageSize)
    const query: ListQuery = { page: lastPage, page_size: pageSize }

    const { result } = renderHook(() => useLatestPage(fetchExecutionPage, query))

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(lastPage).toBe(3)
    expect(result.current.result.total).toBe(total)
    expect((lastPage - 1) * pageSize + result.current.result.rows.length).toBe(total)
  })

  it('opens no second request when the query changes with a page still pending', async () => {
    const first = deferred<ListPage<{ id: string }>>()
    const second = deferred<ListPage<{ id: string }>>()
    const responses = [first, second]
    const signals: (AbortSignal | undefined)[] = []
    let active = 0
    let maxActive = 0
    const fetchPage = vi.fn((_query: ListQuery, signal?: AbortSignal) => {
      signals.push(signal)
      active += 1
      maxActive = Math.max(maxActive, active)
      return responses.shift()!.promise.finally(() => {
        active -= 1
      })
    })

    const pageTwo: ListQuery = { page: 2, page_size: LIST_PAGE_SIZE }
    const { result, rerender } = renderHook(({ query }) => useLatestPage(fetchPage, query), {
      initialProps: { query: FIRST_PAGE },
    })

    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(1))

    // Paging while page 1 is still on the wire - a filter change, a page
    // button, twice on an endpoint slow enough to make it likely. Page 1's
    // query is still running on the server whatever the browser does with its
    // answer, so page 2 may not be issued alongside it (#1095).
    rerender({ query: pageTwo })
    await act(async () => {})
    expect(fetchPage).toHaveBeenCalledTimes(1)

    // Not merely left running: told to stop, which is also how this hook knows
    // the answer is about a query nobody is asking any more.
    expect(signals[0]?.aborted).toBe(true)

    // Page 1's answer arrives. Rendering it would put another page's rows
    // under the current page's controls, and reporting it settled would show
    // them as though they were what page 2 returned.
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
    expect(result.current.result.rows).toEqual([])
    expect(result.current.loading).toBe(true)

    // And only now is page 2 asked for - exactly once, for the rerender and
    // the refetch it triggered between them.
    expect(fetchPage).toHaveBeenCalledTimes(2)
    expect(fetchPage.mock.calls.at(-1)?.[0]).toBe(pageTwo)

    await act(async () => {
      second.resolve(page(['page-2-row'], 120))
    })
    expect(result.current.result.rows).toEqual([{ id: 'page-2-row' }])
    expect(result.current.result.total).toBe(120)

    // The number #1095 is about: two of these were in pg_stat_activity, and a
    // browser discarding one of the answers did not make it one.
    expect(maxActive).toBe(1)
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

  // The list-shaped half of #1095. The poll used to be a `setInterval` beside
  // this hook, and a timer outside it cannot see the fetch the hook does on
  // mount - so a list whose FIRST page took longer than the interval was
  // already being polled while that first page was still on the wire. Asking
  // again had to move inside for the count to be enforceable at all.
  describe('a list endpoint slower than its poll interval', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    /** Rows are still moving, so this list wants to poll - from mount onwards. */
    const pollEvery3s = () => 3000

    it('does not poll a first page that has not come back yet', async () => {
      const pending = deferred<ListPage<{ id: string }>>()
      const fetchPage = vi.fn(() => pending.promise)

      renderHook(() => useLatestPage(fetchPage, FIRST_PAGE, pollEvery3s))
      await vi.waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(1))

      // Six intervals with that page still outstanding.
      await vi.advanceTimersByTimeAsync(18_000)
      expect(fetchPage).toHaveBeenCalledTimes(1)

      // It resumes once the page lands - after a gap that respects how long
      // that page actually took, which is why 20s and not 3s.
      pending.resolve(page(['a'], 1))
      await vi.advanceTimersByTimeAsync(20_000)
      expect(fetchPage.mock.calls.length).toBeGreaterThan(1)
    })
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
  it('is loading for a new query after the first one failed, until that one settles', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      const filtered = deferred<ListPage<{ id: string }>>()
      const FILTERED: ListQuery = { page: 1, page_size: LIST_PAGE_SIZE, statuses: ['failed'] }
      const fetchPage = vi.fn((query: ListQuery) =>
        query === FIRST_PAGE ? Promise.reject(new Error('Network error')) : filtered.promise,
      )

      const { result, rerender } = renderHook(({ query }) => useLatestPage(fetchPage, query), {
        initialProps: { query: FIRST_PAGE },
      })
      await waitFor(() => expect(result.current.failed).toBe(true))
      expect(result.current.loading).toBe(false)

      rerender({ query: FILTERED })

      // The defect: the failure belonged to the old query, yet it alone kept
      // `loading` false, so an empty list read as the new query's answer.
      expect(result.current.failed).toBe(false)
      expect(result.current.loading).toBe(true)

      await act(async () => filtered.resolve(page(['a'], 1)))

      expect(result.current.loading).toBe(false)
      expect(result.current.result.rows).toEqual([{ id: 'a' }])
    } finally {
      consoleError.mockRestore()
    }
  })

  describe('stale: whether the rows on screen answer the current query', () => {
    it('is true while a new query is in flight, with the previous rows still held', async () => {
      const nextPage = deferred<ListPage<{ id: string }>>()
      const fetchPage = vi.fn((query: ListQuery) =>
        query.page === 1 ? Promise.resolve(page(['a'], 2)) : nextPage.promise,
      )
      const SECOND_PAGE: ListQuery = { page: 2, page_size: LIST_PAGE_SIZE }

      const { result, rerender } = renderHook(({ query }) => useLatestPage(fetchPage, query), {
        initialProps: { query: FIRST_PAGE },
      })
      await waitFor(() => expect(result.current.loading).toBe(false))
      expect(result.current.stale).toBe(false)

      rerender({ query: SECOND_PAGE })

      // The defect: `loading` had settled on mount and nothing said the rows
      // on screen now answered a query the operator had left.
      expect(result.current.stale).toBe(true)
      expect(result.current.loading).toBe(false)
      expect(result.current.result.rows).toEqual([{ id: 'a' }])

      await act(async () => nextPage.resolve(page(['b'], 2)))

      expect(result.current.stale).toBe(false)
      expect(result.current.result.rows).toEqual([{ id: 'b' }])
    })

    it('is true when only the fetcher changes, as a caller-owned filter does', async () => {
      const narrowed = deferred<ListPage<{ id: string }>>()
      const everything = vi.fn(async () => page(['a', 'b'], 2))
      const onlyCode = vi.fn(() => narrowed.promise)

      const { result, rerender } = renderHook(
        ({ fetchPage }) => useLatestPage(fetchPage, FIRST_PAGE),
        {
          initialProps: { fetchPage: everything as typeof onlyCode },
        },
      )
      await waitFor(() => expect(result.current.loading).toBe(false))

      rerender({ fetchPage: onlyCode })
      expect(result.current.stale).toBe(true)

      await act(async () => narrowed.resolve(page(['b'], 1)))
      expect(result.current.stale).toBe(false)
    })

    it('stays false while the same query is asked again, so polls do not dim the list', async () => {
      const again = deferred<ListPage<{ id: string }>>()
      const outcomes = [Promise.resolve(page(['a'], 1)), again.promise]
      const fetchPage = vi.fn(() => outcomes.shift()!)

      const { result } = renderHook(() => useLatestPage(fetchPage, FIRST_PAGE))
      await waitFor(() => expect(result.current.loading).toBe(false))

      act(() => result.current.refetch())
      await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(2))

      expect(result.current.stale).toBe(false)
      await act(async () => again.resolve(page(['a'], 1)))
    })

    // A failure settles the request without answering it. Recording it as
    // settled undimmed the old rows under the new filter, with no sign anything
    // had gone wrong.
    it('stays true when the new query fails, until a retry answers it', async () => {
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
      try {
        const SECOND_PAGE: ListQuery = { page: 2, page_size: LIST_PAGE_SIZE }
        const failing = deferred<ListPage<{ id: string }>>()
        const retried = deferred<ListPage<{ id: string }>>()
        const secondPageOutcomes = [failing.promise, retried.promise]
        const fetchPage = vi.fn((query: ListQuery) =>
          query.page === 1 ? Promise.resolve(page(['a'], 2)) : secondPageOutcomes.shift()!,
        )

        const { result, rerender } = renderHook(({ query }) => useLatestPage(fetchPage, query), {
          initialProps: { query: FIRST_PAGE },
        })
        await waitFor(() => expect(result.current.loading).toBe(false))

        rerender({ query: SECOND_PAGE })
        expect(result.current.stale).toBe(true)
        expect(result.current.failed).toBe(false)

        await act(async () => failing.reject(new Error('Network error')))

        expect(result.current.failed).toBe(true)
        expect(result.current.stale).toBe(true)
        expect(result.current.loading).toBe(false)
        expect(result.current.result.rows).toEqual([{ id: 'a' }])

        act(() => result.current.refetch())
        await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(3))
        // Asking again reads as updating, not as the failure still standing.
        expect(result.current.failed).toBe(false)
        expect(result.current.stale).toBe(true)

        await act(async () => retried.resolve(page(['b'], 2)))

        expect(result.current.failed).toBe(false)
        expect(result.current.stale).toBe(false)
        expect(result.current.result.rows).toEqual([{ id: 'b' }])
      } finally {
        consoleError.mockRestore()
      }
    })
  })
})
