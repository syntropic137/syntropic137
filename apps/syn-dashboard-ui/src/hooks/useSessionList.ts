/**
 * Session list data + live updates.
 *
 * The query - filters, paging, facet counts, SSE and polling - is
 * `useServerList`. This hook supplies only what is specific to sessions: the
 * `workflow_id` scope read from the URL, how to fetch a page of them, which
 * events mean the list changed, and the sortable columns.
 *
 * Pages should call this hook and feed the result to presentational
 * components - no fetching, formatting, or SSE handling lives in the page.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listSessions, type SessionListResponse } from '../api/sessions'
import type { ListPage, ListQuery } from '../api/listQuery'
import type { SessionSummary } from '../types'
import { sortSessions } from '../utils/sessionSort'
import {
  useSortUrlState,
  type SortConfig,
  type SortKey,
  type SortState,
} from './useSortUrlState'
import { useServerList, type UseServerListResult } from './useServerList'
import { isTerminalSessionStatus } from '../utils/terminalStatus'

const SESSION_SORT_CONFIG: SortConfig<SortKey> = {
  validKeys: [
    'status',
    'workflow',
    'phase',
    'repos',
    'tokens',
    'cost',
    'duration',
    'started',
  ],
  defaultKey: 'started',
  defaultDir: 'desc',
}

const SESSION_LIVE_EVENTS: ReadonlySet<string> = new Set(['SessionStarted', 'SessionCompleted'])

function isTerminalSession(s: SessionSummary): boolean {
  return isTerminalSessionStatus(s.status)
}

type ApiSessionSummary = NonNullable<SessionListResponse['sessions']>[number]

function toSessionSummary(row: ApiSessionSummary): SessionSummary {
  return {
    ...row,
    workflow_name: row.workflow_name ?? null,
    execution_id: row.execution_id ?? null,
    phase_display: row.phase_display ?? null,
    agent_model: row.agent_model ?? null,
    agent_model_display: row.agent_model_display ?? null,
    repos: row.repos ?? [],
    repos_display: row.repos_display ?? null,
    total_cost_usd: Number(row.total_cost_usd ?? 0),
    duration_seconds: row.duration_seconds ?? null,
    started_at: row.started_at ?? null,
    completed_at: row.completed_at ?? null,
  }
}

export interface UseSessionListResult
  extends Omit<UseServerListResult<SessionSummary>, 'rows' | 'isDefaultFilters'> {
  /** The current page, in the operator's chosen order. */
  sessions: SessionSummary[]
  /** True when filters and sort are at their defaults. */
  isDefaultView: boolean
  sort: SortState<SortKey>
  toggleSort: (key: SortKey) => void
}

export function useSessionList(): UseSessionListResult {
  const [searchParams] = useSearchParams()
  const workflowIdFilter = searchParams.get('workflow_id') ?? ''
  const { sort, toggleSort, isDefault: isDefaultSort } = useSortUrlState(SESSION_SORT_CONFIG)

  const fetchPage = useCallback(
    async (query: ListQuery): Promise<ListPage<SessionSummary>> => {
      const response = await listSessions({
        ...query,
        workflow_id: workflowIdFilter || undefined,
      })
      return {
        rows: (response.sessions ?? []).map(toSessionSummary),
        total: response.total,
        statusCounts: response.status_counts ?? {},
      }
    },
    [workflowIdFilter],
  )

  const { rows, isDefaultFilters, ...list } = useServerList({
    fetchPage,
    scopeKey: workflowIdFilter,
    liveEvents: SESSION_LIVE_EVENTS,
    isTerminal: isTerminalSession,
  })

  // Reorders the page the server sent; the endpoint offers no sort parameter,
  // so a non-default sort orders these 50 rows and not the collection.
  const sessions = useMemo(
    () => sortSessions(rows, sort.key, sort.dir),
    [rows, sort.key, sort.dir],
  )

  return {
    ...list,
    sessions,
    isDefaultView: isDefaultSort && isDefaultFilters,
    sort,
    toggleSort,
  }
}
