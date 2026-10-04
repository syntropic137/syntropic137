/**
 * The answer to the most recent query, and only that one - kept current.
 *
 * Four things ask these lists to refetch - the filter bar, paging, SSE and the
 * poll that keeps running rows ticking. An answer to a query the caller has
 * moved on from would put another page's rows on screen under the current
 * page's controls, so it is discarded rather than rendered.
 *
 * Which answers those are is not decided here. `useSerialRefresh` aborts the
 * request it abandons when the query changes, so `signal.aborted` IS the
 * question "has this been overtaken" - already answered, by the only thing
 * that knows. This hook used to count its own requests and compare, which was
 * a second opinion on the same fact and could differ from it.
 *
 * Asking again lives here too, rather than in a timer beside this hook, for a
 * reason worth keeping: a timer outside cannot see the fetch this hook does on
 * mount, so a list whose first page took longer than the interval was already
 * being polled while its first page was still on the wire (#1095). Every ask -
 * mount, new query, SSE, poll - now goes through one `useSerialRefresh`, which
 * is what makes "one request at a time" true of the list rather than of each
 * trigger separately.
 *
 * Callers see a page of rows, whether those rows answer the query they are
 * showing, and a way to ask again. They do not see the sequencing, and cannot
 * get it wrong.
 *
 * "Is something on the wire" is deliberately NOT what is reported: SSE and the
 * poll are always about to ask again, and a list that dimmed on every tick
 * would be telling the operator nothing. What matters is whether the rows on
 * screen are the answer to the controls on screen. A filter change makes them
 * not, until its answer lands - and a page that kept showing them as settled
 * read as a filter that did nothing.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useEffect, useState } from 'react'
import type { ListPage, ListQuery } from '../api/listQuery'
import { ifStillWanted } from './serialRefreshLoop'
import { useSerialRefresh } from './useSerialRefresh'

interface SettledRequest<TRow> {
  fetchPage: (query: ListQuery, signal?: AbortSignal) => Promise<ListPage<TRow>>
  query: ListQuery
}

const EMPTY_PAGE: ListPage<never> = {
  rows: [],
  total: 0,
  statusCounts: {},
  excludedUndated: 0,
}

export interface LatestPageState<TRow> {
  /** The newest page received. `EMPTY_PAGE` until the first one lands. */
  result: ListPage<TRow>
  /** Nothing has settled yet, so there are no rows worth showing. */
  loading: boolean
  /**
   * `result` answers a query the caller has since left - a filter, a page or a
   * scope changed and the new answer is still on its way. The rows are still
   * worth showing, as the previous answer. Never true while `loading` is.
   */
  stale: boolean
  /** Ask again for the same query. Stable for the life of the component. */
  refetch: () => void
}

/**
 * @param fetchPage Must be referentially stable (wrap in `useCallback`) - it
 *   is a dependency of the fetch effect. Pass `signal` on to the request: the
 *   answer is discarded either way, but only the signal stops the server
 *   producing it.
 * @param query Refetched whenever this changes identity, so it must be
 *   memoised: `useListQuery` returns one that is.
 * @param pollIntervalFor Shortest gap between polls given the rows currently on
 *   screen, or `null` to rely on SSE and explicit refetches alone. Taking the
 *   rows rather than a number keeps the decision honest: what is on screen is
 *   what decides, and only this hook knows it. The real gap also respects how
 *   slow the endpoint is actually being.
 */
export function useLatestPage<TRow>(
  fetchPage: (query: ListQuery, signal?: AbortSignal) => Promise<ListPage<TRow>>,
  query: ListQuery,
  pollIntervalFor: (rows: TRow[]) => number | null = () => null,
): LatestPageState<TRow> {
  const [result, setResult] = useState<ListPage<TRow>>(EMPTY_PAGE)
  // Which request the page on screen settled for. Both halves, because a
  // caller's own narrowing (an artifact type, say) arrives as a new
  // `fetchPage` rather than a new `query`.
  const [settledFor, setSettledFor] = useState<SettledRequest<TRow> | null>(null)

  const fetchLatest = useCallback(
    (signal: AbortSignal) =>
      fetchPage(query, signal)
        .then(ifStillWanted(signal, (next: ListPage<TRow>) => setResult(next)))
        // The abort itself included: the request was cancelled on purpose, and
        // reporting it as a failure of this list would be a lie about a query
        // nobody asked for any more.
        .catch(ifStillWanted(signal, (error: unknown) => console.error(error)))
        // Left unsettled on purpose when overtaken. The replacement is what
        // this list is waiting for now, and settling here would show the
        // previous query's rows as though they answered the current one.
        .finally(ifStillWanted<void>(signal, () => setSettledFor({ fetchPage, query }))),
    [fetchPage, query],
  )

  const { refetch } = useSerialRefresh({
    fetch: fetchLatest,
    pollIntervalMs: pollIntervalFor(result.rows),
  })

  useEffect(() => {
    refetch()
  }, [refetch, fetchLatest])

  const loading = settledFor === null
  const stale =
    settledFor !== null && (settledFor.fetchPage !== fetchPage || settledFor.query !== query)

  return { result, loading, stale, refetch }
}
