/**
 * The query a list surface is asking right now.
 *
 * A caller states which collection it is looking at (`scopeKey`) and gets back
 * a `ListQuery` to issue, plus the controls that change it. What it never has
 * to know is how any of that was decided: that the search term is settled
 * before it travels, that a status set becomes a sorted array, that a time
 * window becomes an ISO bound with an offset, or that asking about a different
 * collection means asking for its first page.
 *
 * Every one of those is a way for two list surfaces to disagree, which is what
 * #1159 was, so each is settled in one place here.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ListQuery } from '../api/listQuery'
import type { TimeWindow } from '../types'
import {
  DEFAULT_TIME_WINDOW,
  timeWindowToStartedAfter,
  useFilterUrlState,
} from './useFilterUrlState'
import { useResetView } from './useResetView'

/** Long enough that typing a word is one request, short enough to feel live. */
export const SEARCH_DEBOUNCE_MS = 300

export const LIST_PAGE_SIZE = 50

/**
 * The sizes an operator can pick on Executions and Sessions (feedback
 * 60d9f990). The API caps a page at 200.
 */
export const RUN_LIST_PAGE_SIZES: readonly number[] = [50, 100]

/**
 * Both open at 50; 100 is the operator's choice. The owner's bound was "100 by
 * default unless it costs over 1.5x of 50". On the E2 dataset (p95 of 20, three
 * runs) /executions measured 1.59x, 1.76x, 1.83x and /sessions 0.87x, 1.24x,
 * 1.71x, so neither clears it reliably (PR #1785 has the tables).
 */
export const SESSION_LIST_PAGE_SIZE = LIST_PAGE_SIZE
export const EXECUTION_LIST_PAGE_SIZE = LIST_PAGE_SIZE

export interface ListQueryState {
  /**
   * The query to issue now. Referentially stable until something that defines
   * it changes, so it can be a fetch dependency directly.
   */
  query: ListQuery
  /** Move within the current collection. Clamped at page 1. */
  setPage: (page: number) => void
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
}

/** Settle on a value only once it has stopped changing for `delayMs`. */
export function useDebounced<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return settled
}

/**
 * The page being viewed within one collection, identified by `collectionKey`.
 *
 * A page number means nothing except relative to its collection, so any change
 * of collection IS page 1. Derived in render rather than reset in an effect,
 * which would fetch the old page of the new collection first. And the held page
 * is dropped the moment the collection changes, not merely hidden: keeping it
 * would restore page 3 on returning to a collection seen before (page 3 ->
 * search -> clear search), which is a change of collection like any other.
 */
export interface CollectionPage {
  page: number
  /** Move within the current collection. Clamped at page 1. */
  setPage: (page: number) => void
}

export function useCollectionPage(collectionKey: string): CollectionPage {
  const [pageState, setPageState] = useState({ collectionKey, page: 1 })
  if (pageState.collectionKey !== collectionKey) {
    // Adjusting state while rendering, as React documents for a changed input:
    // this render already reads page 1, and the stale page is forgotten.
    setPageState({ collectionKey, page: 1 })
  }
  const page = pageState.collectionKey === collectionKey ? pageState.page : 1
  const setPage = useCallback(
    (next: number) => setPageState({ collectionKey, page: Math.max(1, next) }),
    [collectionKey],
  )
  return { page, setPage }
}

/**
 * @param scopeKey Identity of any narrowing the caller applies that this hook
 *   cannot see, such as Sessions' `workflow_id`. Changing it selects a
 *   different collection, exactly as a shared filter does.
 * @param pageSize Rows per page. Changing it returns to page 1, since the
 *   old page number addresses different rows at a different size.
 */
export function useListQuery(scopeKey: string, pageSize: number = LIST_PAGE_SIZE): ListQueryState {
  const { selectedStatuses, timeWindow, toggleStatus, setTimeWindow, clearStatuses } =
    useFilterUrlState()
  const resetView = useResetView()

  const [searchQuery, setSearchQuery] = useState('')
  const search = useDebounced(searchQuery.trim(), SEARCH_DEBOUNCE_MS)

  const statusesKey = useMemo(
    () => Array.from(selectedStatuses).sort().join(','),
    [selectedStatuses],
  )
  const statuses = useMemo(
    () => (statusesKey ? statusesKey.split(',') : undefined),
    [statusesKey],
  )

  // Resolved once per window choice rather than per request: a lower bound
  // recomputed on every 5s poll would slide the oldest end of the collection
  // out from under the page offsets while an operator is paging through it.
  const startedAfter = useMemo(() => timeWindowToStartedAfter(timeWindow), [timeWindow])

  // Which collection is being paged. See useCollectionPage.
  const collectionKey = [scopeKey, statusesKey, startedAfter ?? '', search, pageSize].join(' ')
  const { page, setPage } = useCollectionPage(collectionKey)

  const query = useMemo<ListQuery>(
    () => ({
      page,
      page_size: pageSize,
      statuses,
      started_after: startedAfter,
      q: search || undefined,
    }),
    [page, pageSize, statuses, startedAfter, search],
  )

  return {
    query,
    setPage,
    searchQuery,
    setSearchQuery,
    selectedStatuses,
    toggleStatus,
    clearStatuses,
    timeWindow,
    setTimeWindow,
    resetView,
    isDefaultFilters: selectedStatuses.size === 0 && timeWindow === DEFAULT_TIME_WINDOW,
  }
}
