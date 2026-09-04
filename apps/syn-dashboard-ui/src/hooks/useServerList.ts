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
 * What a caller does NOT get is a hook into how any of that is decided. The
 * filter-to-query mapping, the page reset, the debounce and the ordering of
 * overlapping responses are all settled in here, because every one of them is
 * a way for the two lists to disagree again.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ListPage, ListQuery } from '../api/listQuery'
import type { SSEEventFrame, TimeWindow } from '../types'
import { useActivityStream } from './useActivityStream'
import { timeWindowToStartedAfter, useFilterUrlState } from './useFilterUrlState'
import { useRefetchWhileRunning } from './useRefetchWhileRunning'
import { useResetView } from './useResetView'
import { useThrottledRefetch } from './useThrottledRefetch'

const REFETCH_THROTTLE_MS = 500
const POLL_INTERVAL_MS = 5000
/** Long enough that typing a word is one request, short enough to feel live. */
const SEARCH_DEBOUNCE_MS = 300

export const LIST_PAGE_SIZE = 50

const EMPTY_PAGE: ListPage<never> = { rows: [], total: 0, statusCounts: {} }

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

/** Settle on a value only once it has stopped changing for `delayMs`. */
function useDebounced<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return settled
}

export function useServerList<TRow>({
  fetchPage,
  scopeKey = '',
  liveEvents,
  isTerminal,
}: UseServerListOptions<TRow>): UseServerListResult<TRow> {
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
  const queryKey = [scopeKey, statusesKey, startedAfter ?? '', search].join(' ')
  const [pageState, setPageState] = useState({ queryKey, page: 1 })
  const page = pageState.queryKey === queryKey ? pageState.page : 1
  const setPage = useCallback(
    (next: number) => setPageState({ queryKey, page: Math.max(1, next) }),
    [queryKey],
  )

  const [result, setResult] = useState<ListPage<TRow>>(EMPTY_PAGE)
  const [loading, setLoading] = useState(true)

  // Four things refetch this list - the filter bar, paging, SSE and two
  // pollers - so responses overlap routinely. Only the newest request may
  // write; an earlier one landing late would put another page's rows on screen.
  const latestRequest = useRef(0)

  const refetch = useCallback(() => {
    const request = ++latestRequest.current
    fetchPage({
      page,
      page_size: LIST_PAGE_SIZE,
      statuses,
      started_after: startedAfter,
      q: search || undefined,
    })
      .then((next) => {
        if (request === latestRequest.current) setResult(next)
      })
      .catch((error) => {
        if (request === latestRequest.current) console.error(error)
      })
      .finally(() => {
        if (request === latestRequest.current) setLoading(false)
      })
  }, [fetchPage, page, statuses, startedAfter, search])

  useEffect(() => {
    refetch()
  }, [refetch])

  const scheduleRefetch = useThrottledRefetch(refetch, REFETCH_THROTTLE_MS)

  const handleFrame = useCallback(
    (frame: SSEEventFrame) => {
      if (frame.type === 'event' && liveEvents.has(frame.event_type)) scheduleRefetch()
    },
    [liveEvents, scheduleRefetch],
  )

  const { connected, lastEventAt } = useActivityStream({
    onEvent: handleFrame,
    filter: (eventType) => liveEvents.has(eventType),
  })

  useEffect(() => {
    if (connected) return
    const id = setInterval(refetch, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [connected, refetch])

  // SSE only fires on Started/Completed, but Lane 2 (tokens/cost/duration)
  // updates continuously. Poll while any row on this page is non-terminal.
  useRefetchWhileRunning({ items: result.rows, isTerminal, refetch })

  return {
    rows: result.rows,
    loading,
    total: result.total,
    page,
    pageSize: LIST_PAGE_SIZE,
    totalPages: Math.max(1, Math.ceil(result.total / LIST_PAGE_SIZE)),
    setPage,
    statusCounts: result.statusCounts,
    searchQuery,
    setSearchQuery,
    selectedStatuses,
    toggleStatus,
    clearStatuses,
    timeWindow,
    setTimeWindow,
    resetView,
    isDefaultFilters: selectedStatuses.size === 0 && timeWindow === '24h',
    connected,
    lastEventAt,
  }
}
