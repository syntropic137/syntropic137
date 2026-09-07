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
const SEARCH_DEBOUNCE_MS = 300

export const LIST_PAGE_SIZE = 50

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
function useDebounced<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return settled
}

/**
 * @param scopeKey Identity of any narrowing the caller applies that this hook
 *   cannot see, such as Sessions' `workflow_id`. Changing it selects a
 *   different collection, exactly as a shared filter does.
 */
export function useListQuery(scopeKey: string): ListQueryState {
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

  // Which collection is being paged. A page number means nothing except
  // relative to this, so a change to it IS page 1 - derived rather than reset
  // in an effect, which would fetch the old page first and then correct it.
  const collectionKey = [scopeKey, statusesKey, startedAfter ?? '', search].join(' ')
  const [pageState, setPageState] = useState({ collectionKey, page: 1 })
  const page = pageState.collectionKey === collectionKey ? pageState.page : 1
  const setPage = useCallback(
    (next: number) => setPageState({ collectionKey, page: Math.max(1, next) }),
    [collectionKey],
  )

  const query = useMemo<ListQuery>(
    () => ({
      page,
      page_size: LIST_PAGE_SIZE,
      statuses,
      started_after: startedAfter,
      q: search || undefined,
    }),
    [page, statuses, startedAfter, search],
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
