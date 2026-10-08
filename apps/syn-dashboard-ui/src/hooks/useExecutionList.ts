/**
 * Execution list data + live updates.
 *
 * The query - filters, paging, facet counts, SSE and polling - is
 * `useServerList`. This hook supplies only what is specific to executions:
 * how to fetch a page of them, which events mean the list changed, and the
 * sortable columns.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listAllExecutions, type EvalFilter } from '../api/executions'
import type { ListPage, ListQuery } from '../api/listQuery'
import type { ExecutionListItem, ExecutionListResponse } from '../types'
import { sortExecutions } from '../utils/executionSort'
import {
  useSortUrlState,
  type SortConfig,
  type SortState,
} from './useSortUrlState'
import { RUN_LIST_PAGE_SIZE, useServerList, type UseServerListResult } from './useServerList'
import { isTerminalExecutionStatus } from '../utils/terminalStatus'

const EXECUTION_LIVE_EVENTS: ReadonlySet<string> = new Set([
  'WorkflowExecutionStarted',
  'WorkflowCompleted',
  'WorkflowFailed',
])

export type ExecutionSortKey =
  | 'status'
  | 'workflow'
  | 'progress'
  | 'tokens'
  | 'cost'
  | 'duration'
  | 'repos'
  | 'started'

const EXECUTION_SORT_CONFIG: SortConfig<ExecutionSortKey> = {
  validKeys: ['status', 'workflow', 'progress', 'tokens', 'cost', 'duration', 'repos', 'started'],
  defaultKey: 'started',
  defaultDir: 'desc',
}

function isTerminalExecution(e: ExecutionListItem): boolean {
  return isTerminalExecutionStatus(e.status)
}

function toExecutionListItem(
  row: ExecutionListResponse['executions'][number],
): ExecutionListItem {
  return {
    ...row,
    started_at: row.started_at ?? null,
    completed_at: row.completed_at ?? null,
    total_cost_usd: Number(row.total_cost_usd),
    duration_seconds: row.duration_seconds ?? null,
    repos: row.repos ?? [],
    repos_display: row.repos_display ?? null,
    eval: row.eval ?? null,
    start_queue: row.start_queue ?? null,
  }
}

const EVAL_FILTER_PARAM = 'evals'

function parseEvalFilter(raw: string | null): EvalFilter {
  return raw === 'only' || raw === 'hide' ? raw : 'all'
}

/** The eval filter, held in the URL so a filtered view can be shared. */
function useEvalFilterUrlState(): [EvalFilter, (next: EvalFilter) => void] {
  const [searchParams, setSearchParams] = useSearchParams()
  const evalFilter = parseEvalFilter(searchParams.get(EVAL_FILTER_PARAM))
  const setEvalFilter = useCallback(
    (next: EvalFilter) => {
      setSearchParams(
        (prev) => {
          const out = new URLSearchParams(prev)
          if (next === 'all') out.delete(EVAL_FILTER_PARAM)
          else out.set(EVAL_FILTER_PARAM, next)
          return out
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )
  return [evalFilter, setEvalFilter]
}

export interface UseExecutionListResult
  extends Omit<UseServerListResult<ExecutionListItem>, 'rows' | 'isDefaultFilters'> {
  /** The current page, in the operator's chosen order. */
  executions: ExecutionListItem[]
  /** True when filters and sort are at their defaults. */
  isDefaultView: boolean
  /** Every run, only eval runs, or only runs in no eval. */
  evalFilter: EvalFilter
  setEvalFilter: (next: EvalFilter) => void
  sort: SortState<ExecutionSortKey>
  toggleSort: (key: ExecutionSortKey) => void
}

export function useExecutionList(): UseExecutionListResult {
  const { sort, toggleSort, isDefault: isDefaultSort } = useSortUrlState(EXECUTION_SORT_CONFIG)
  const [evalFilter, setEvalFilter] = useEvalFilterUrlState()

  const fetchPage = useCallback(
    async (query: ListQuery, signal?: AbortSignal): Promise<ListPage<ExecutionListItem>> => {
      const response = await listAllExecutions(query, evalFilter, signal)
      return {
        rows: response.executions.map(toExecutionListItem),
        total: response.total,
        statusCounts: response.status_counts ?? {},
        excludedUndated: response.excluded_undated,
      }
    },
    [evalFilter],
  )

  // The eval filter selects a different collection, which `useListQuery`
  // turns into page 1.
  const { rows, isDefaultFilters, ...list } = useServerList({
    fetchPage,
    scopeKey: evalFilter,
    pageSize: RUN_LIST_PAGE_SIZE,
    liveEvents: EXECUTION_LIVE_EVENTS,
    isTerminal: isTerminalExecution,
  })

  // Reorders the page the server sent; the endpoint offers no sort parameter,
  // so a non-default sort orders this page's rows and not the collection.
  const executions = useMemo(
    () => sortExecutions(rows, sort.key, sort.dir),
    [rows, sort.key, sort.dir],
  )

  return {
    ...list,
    executions,
    isDefaultView: isDefaultSort && isDefaultFilters && evalFilter === 'all',
    evalFilter,
    setEvalFilter,
    sort,
    toggleSort,
  }
}
