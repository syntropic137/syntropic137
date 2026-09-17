/**
 * The answer to the most recent query, and only that one - kept current.
 *
 * Four things ask these lists to refetch - the filter bar, paging, SSE and the
 * poll that keeps running rows ticking - so responses overlap routinely. An
 * earlier one landing late would put another page's rows on screen under the
 * current page's controls, so a response that has been overtaken is discarded
 * rather than rendered.
 *
 * Asking again lives here too, rather than in a timer beside this hook, for a
 * reason worth keeping: a timer outside cannot see the fetch this hook does on
 * mount, so a list whose first page took longer than the interval was already
 * being polled while its first page was still on the wire (#1095). Every ask -
 * mount, new query, SSE, poll - now goes through one `useSerialRefresh`, which
 * is what makes "one request at a time" true of the list rather than of each
 * trigger separately.
 *
 * Callers see a page of rows, whether one is still on its way, and a way to
 * ask again. They do not see the sequencing, and cannot get it wrong.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { ListPage, ListQuery } from '../api/listQuery'
import { useSerialRefresh } from './useSerialRefresh'

const EMPTY_PAGE: ListPage<never> = { rows: [], total: 0, statusCounts: {}, excludedUndated: 0 }

export interface LatestPageState<TRow> {
  /** The newest page received. `EMPTY_PAGE` until the first one lands. */
  result: ListPage<TRow>
  loading: boolean
  /** Ask again for the same query. Stable for the life of the component. */
  refetch: () => void
}

/**
 * @param fetchPage Must be referentially stable (wrap in `useCallback`) - it
 *   is a dependency of the fetch effect.
 * @param query Refetched whenever this changes identity, so it must be
 *   memoised: `useListQuery` returns one that is.
 * @param pollIntervalFor Shortest gap between polls given the rows currently on
 *   screen, or `null` to rely on SSE and explicit refetches alone. Taking the
 *   rows rather than a number keeps the decision honest: what is on screen is
 *   what decides, and only this hook knows it. The real gap also respects how
 *   slow the endpoint is actually being.
 */
export function useLatestPage<TRow>(
  fetchPage: (query: ListQuery) => Promise<ListPage<TRow>>,
  query: ListQuery,
  pollIntervalFor: (rows: TRow[]) => number | null = () => null,
): LatestPageState<TRow> {
  const [result, setResult] = useState<ListPage<TRow>>(EMPTY_PAGE)
  const [loading, setLoading] = useState(true)
  const latestRequest = useRef(0)

  const fetchLatest = useCallback(() => {
    const request = ++latestRequest.current
    const isLatest = () => request === latestRequest.current
    return fetchPage(query)
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

  const { refetch } = useSerialRefresh({
    fetch: fetchLatest,
    pollIntervalMs: pollIntervalFor(result.rows),
  })

  useEffect(() => {
    refetch()
  }, [refetch, fetchLatest])

  return { result, loading, refetch }
}
