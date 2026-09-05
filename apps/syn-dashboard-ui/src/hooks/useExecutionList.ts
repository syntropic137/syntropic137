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
import { listAllExecutions } from '../api/executions'
import type { ListPage, ListQuery } from '../api/listQuery'
import type { ExecutionListItem, ExecutionListResponse } from '../types'
import { sortExecutions } from '../utils/executionSort'
import {
  useSortUrlState,
  type SortConfig,
  type SortState,
} from './useSortUrlState'
import { useServerList, type UseServerListResult } from './useServerList'
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
  }
}

export interface UseExecutionListResult
  extends Omit<UseServerListResult<ExecutionListItem>, 'rows' | 'isDefaultFilters'> {
  /** The current page, in the operator's chosen order. */
  executions: ExecutionListItem[]
  /** True when filters and sort are at their defaults. */
  isDefaultView: boolean
  sort: SortState<ExecutionSortKey>
  toggleSort: (key: ExecutionSortKey) => void
}

export function useExecutionList(): UseExecutionListResult {
  const { sort, toggleSort, isDefault: isDefaultSort } = useSortUrlState(EXECUTION_SORT_CONFIG)

  const fetchPage = useCallback(
    async (query: ListQuery): Promise<ListPage<ExecutionListItem>> => {
      const response = await listAllExecutions(query)
      return {
        rows: response.executions.map(toExecutionListItem),
        total: response.total,
        statusCounts: response.status_counts ?? {},
      }
    },
    [],
  )

  const { rows, isDefaultFilters, ...list } = useServerList({
    fetchPage,
    liveEvents: EXECUTION_LIVE_EVENTS,
    isTerminal: isTerminalExecution,
  })

  // Reorders the page the server sent; the endpoint offers no sort parameter,
  // so a non-default sort orders these 50 rows and not the collection.
  const executions = useMemo(
    () => sortExecutions(rows, sort.key, sort.dir),
    [rows, sort.key, sort.dir],
  )

  return {
    ...list,
    executions,
    isDefaultView: isDefaultSort && isDefaultFilters,
    sort,
    toggleSort,
  }
}
