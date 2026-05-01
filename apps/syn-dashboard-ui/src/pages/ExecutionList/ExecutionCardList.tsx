/**
 * Mobile card-list rendering of executions.
 *
 * Thin adapter over ResourceCardList: contributes a renderCard fn that maps
 * ExecutionListItem → ExecutionCard inner content. Wrapper, selection, and
 * tap-to-detail behaviour are shared with Sessions via ResourceCardList.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { ResourceCardList } from '../../components'
import type { SelectionProps } from '../../components/ResourceTable/types'
import type { ExecutionListItem } from '../../types'
import { ExecutionCard } from './ExecutionCard'

interface ExecutionCardListProps {
  rows: ExecutionListItem[]
  loading: boolean
  emptyState: ReactNode
  selection?: SelectionProps
}

export function ExecutionCardList({ rows, loading, emptyState, selection }: ExecutionCardListProps) {
  const navigate = useNavigate()
  return (
    <ResourceCardList<ExecutionListItem>
      rows={rows}
      loading={loading}
      emptyState={emptyState}
      selection={selection}
      getRowId={(e) => e.workflow_execution_id}
      onRowClick={(e) => navigate(`/executions/${e.workflow_execution_id}`)}
      renderCard={(e) => <ExecutionCard exec={e} />}
    />
  )
}
