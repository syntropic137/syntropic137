/**
 * The answer to the most recent query, and only that one.
 *
 * Four things ask these lists to refetch - the filter bar, paging, SSE and two
 * pollers - so responses overlap routinely. An earlier one landing late would
 * put another page's rows on screen under the current page's controls, so a
 * response that has been overtaken is discarded rather than rendered.
 *
 * Callers see a page of rows, whether one is still on its way, and a way to
 * ask again. They do not see the sequencing, and cannot get it wrong.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { ListPage, ListQuery } from '../api/listQuery'

const EMPTY_PAGE: ListPage<never> = { rows: [], total: 0, statusCounts: {}, excludedUndated: 0 }

export interface LatestPageState<TRow> {
  /** The newest page received. `EMPTY_PAGE` until the first one lands. */
  result: ListPage<TRow>
  loading: boolean
  /** Ask again for the same query. Stable while the query is unchanged. */
  refetch: () => void
}

/**
 * @param fetchPage Must be referentially stable (wrap in `useCallback`) - it
 *   is a dependency of the fetch effect.
 * @param query Refetched whenever this changes identity, so it must be
 *   memoised: `useListQuery` returns one that is.
 */
export function useLatestPage<TRow>(
  fetchPage: (query: ListQuery) => Promise<ListPage<TRow>>,
  query: ListQuery,
): LatestPageState<TRow> {
  const [result, setResult] = useState<ListPage<TRow>>(EMPTY_PAGE)
  const [loading, setLoading] = useState(true)
  const latestRequest = useRef(0)

  const refetch = useCallback(() => {
    const request = ++latestRequest.current
    const isLatest = () => request === latestRequest.current
    fetchPage(query)
      .then((next) => {
        if (isLatest()) setResult(next)
      })
      .catch((error) => {
        if (isLatest()) console.error(error)
      })
      .finally(() => {
        if (isLatest()) setLoading(false)
      })
  }, [fetchPage, query])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { result, loading, refetch }
}
