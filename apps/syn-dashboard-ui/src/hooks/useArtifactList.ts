/**
 * Artifact list data + live updates.
 *
 * The query - paging, the time window, search, SSE and polling - is
 * `useServerList`, the same one Executions and Sessions use. This hook
 * supplies only what is specific to artifacts: the `workflow_id`/`phase_id`
 * scope read from the URL, the artifact-type filter, and how to fetch a page.
 *
 * It used to fetch `limit: 100` once and filter the result in the browser, so
 * the type dropdown, the search box and the row count all described the newest
 * 100 rows rather than the collection - the #1159 shape, on the endpoint that
 * could not answer any other way until #1204.
 *
 * Artifacts have no status, so the shared status chips do not apply. The facet
 * dimension the server tallies is `artifact_type`, and it arrives in
 * `statusCounts` because that is what `ListPage` calls its facet counts.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listArtifactPage } from '../api/artifacts'
import type { ListPage, ListQuery } from '../api/listQuery'
import type { ArtifactSummary } from '../types'
import { useServerList, type UseServerListResult } from './useServerList'

const ARTIFACT_LIVE_EVENTS: ReadonlySet<string> = new Set(['ArtifactCreated'])

/** An artifact is written once and never changes, so nothing is still moving. */
function isTerminalArtifact(): boolean {
  return true
}

export interface UseArtifactListResult
  extends Omit<UseServerListResult<ArtifactSummary>, 'rows'> {
  /** The current page of artifacts, newest first. */
  artifacts: ArtifactSummary[]
  /** Empty means every type. */
  typeFilter: string
  setTypeFilter: (type: string) => void
  /** Matching artifacts tallied by type, over the collection, not the page. */
  typeCounts: Record<string, number>
}

export function useArtifactList(): UseArtifactListResult {
  const [searchParams] = useSearchParams()
  const workflowIdFilter = searchParams.get('workflow_id') ?? ''
  const phaseIdFilter = searchParams.get('phase_id') ?? ''

  const [typeFilter, setTypeFilter] = useState('')

  const fetchPage = useCallback(
    async (query: ListQuery): Promise<ListPage<ArtifactSummary>> => {
      const response = await listArtifactPage(query, {
        workflow_id: workflowIdFilter || undefined,
        phase_id: phaseIdFilter || undefined,
        artifact_type: typeFilter || undefined,
      })
      return {
        rows: response.artifacts,
        total: response.total,
        statusCounts: response.type_counts,
      }
    },
    [workflowIdFilter, phaseIdFilter, typeFilter],
  )

  // Every narrowing this hook applies itself: changing any of them selects a
  // different collection, which `useListQuery` turns into page 1.
  const { rows, ...list } = useServerList({
    fetchPage,
    scopeKey: [workflowIdFilter, phaseIdFilter, typeFilter].join(' '),
    liveEvents: ARTIFACT_LIVE_EVENTS,
    isTerminal: isTerminalArtifact,
  })

  return {
    ...list,
    artifacts: rows,
    typeFilter,
    setTypeFilter,
    typeCounts: list.statusCounts,
  }
}
