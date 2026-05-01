/**
 * Executions table — thin adapter over the generic ResourceTable.
 *
 * Same pattern as SessionTable: per-row navigation, optional sort + selection,
 * shared chrome via the ResourceTable primitive.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useNavigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { ResourceTable } from '../../components'
import type {
  ResourceTableProps,
  SelectionProps,
  SortProps,
} from '../../components/ResourceTable/types'
import type { ExecutionListItem } from '../../types'
import type { ExecutionSortKey } from '../../hooks/useExecutionList'
import { EXECUTION_COLUMNS } from './executionColumns'

interface ExecutionTableProps {
  rows: ExecutionListItem[]
  loading: boolean
  emptyState: ReactNode
  selection?: SelectionProps
  sort?: SortProps<ExecutionSortKey>
}

export function ExecutionTable({
  rows,
  loading,
  emptyState,
  selection,
  sort,
}: ExecutionTableProps) {
  const navigate = useNavigate()
  const props: ResourceTableProps<ExecutionListItem, ExecutionSortKey> = {
    rows,
    columns: EXECUTION_COLUMNS,
    loading,
    emptyState,
    getRowId: (e) => e.workflow_execution_id,
    onRowClick: (e) => navigate(`/executions/${e.workflow_execution_id}`),
    selection,
    sort,
  }
  return <ResourceTable {...props} />
}
