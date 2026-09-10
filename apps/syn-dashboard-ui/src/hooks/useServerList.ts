/**
 * A list surface backed by one server query: filtered, paged, and live.
 *
 * Sessions and Executions are the same list twice - the same filter bar, the
 * same chips, the same SSE refresh, the same fallback polling - and they were
 * written twice. They then drifted, and the drift was the defect: Executions
 * asked the server for one unfiltered page of 50 and narrowed it in the
 * browser, so the time window, the status chips and the row count all
 * described the newest 50 rows rather than the collection (#1159). With ~360
 * executions, "235 completed" rendered as 35 and the oldest row was
 * unreachable by any interaction.
 *
 * So the query lives here once. A caller supplies only what is genuinely its
 * own - how to fetch a page of ITS resource, which events mean its list
 * changed, and which of its rows are still moving - and gets back rows a
 * server chose, a total it can page against, and facet counts it did not have
 * to compute.
 *
 * What a caller does NOT get is a hook into how any of that is decided. This
 * function is composition and nothing else; each decision belongs to one of
 * three units and none of them is reachable from a page:
 *
 *   - `useListQuery`    what to ask for, and which collection that is
 *   - `useLatestPage`   asking, and ignoring answers that were overtaken
 *   - `useLiveRefresh`  when to ask again
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import type { ListPage, ListQuery } from '../api/listQuery'
import type { TimeWindow } from '../types'
import { LIST_PAGE_SIZE, useListQuery } from './useListQuery'
import { useLatestPage } from './useLatestPage'
import { useLiveRefresh } from './useLiveRefresh'

export { LIST_PAGE_SIZE }

export interface UseServerListOptions<TRow> {
  /**
   * Fetch one page. Must be referentially stable (wrap in `useCallback`) -
   * it is a dependency of the fetch effect.
   */
  fetchPage: (query: ListQuery) => Promise<ListPage<TRow>>
  /**
   * Identity of any narrowing the caller applies inside `fetchPage` that this
   * hook cannot see, such as Sessions' `workflow_id`. Changing it re-fetches
   * and returns to page 1, exactly as a shared filter does.
   */
  scopeKey?: string
  /** Event types that mean "this list changed". */
  liveEvents: ReadonlySet<string>
  /** False while a row's Lane 2 numbers are still moving, which keeps polling. */
  isTerminal: (row: TRow) => boolean
}

export interface UseServerListResult<TRow> {
  /** The rows the server put on this page, newest first. */
  rows: TRow[]
  loading: boolean
  /** Rows matching the filters across every page. */
  total: number
  page: number
  pageSize: number
  totalPages: number
  setPage: (page: number) => void
  /** Server-side facet counts, over the collection rather than the page. */
  statusCounts: Record<string, number>
  /** Matching rows the window could not judge for want of a timestamp (#1215). */
  excludedUndated: number
  searchQuery: string
  setSearchQuery: (query: string) => void
  selectedStatuses: Set<string>
  toggleStatus: (status: string) => void
  clearStatuses: () => void
  timeWindow: TimeWindow
  setTimeWindow: (next: TimeWindow) => void
  /** Restore default filters AND default sort. */
  resetView: () => void
  /** True when the shared filters are at their defaults; sort is the caller's. */
  isDefaultFilters: boolean
  connected: boolean
  lastEventAt: number | null
}

export function useServerList<TRow>({
  fetchPage,
  scopeKey = '',
  liveEvents,
  isTerminal,
}: UseServerListOptions<TRow>): UseServerListResult<TRow> {
  const { query, ...filters } = useListQuery(scopeKey)
  const { result, loading, refetch } = useLatestPage(fetchPage, query)
  const { connected, lastEventAt } = useLiveRefresh({
    refetch,
    liveEvents,
    rows: result.rows,
    isTerminal,
  })

  return {
    ...filters,
    rows: result.rows,
    loading,
    total: result.total,
    statusCounts: result.statusCounts,
    excludedUndated: result.excludedUndated,
    page: query.page,
    pageSize: query.page_size,
    totalPages: Math.max(1, Math.ceil(result.total / query.page_size)),
    connected,
    lastEventAt,
  }
}
