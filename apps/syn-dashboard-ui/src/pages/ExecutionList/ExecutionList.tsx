/**
 * Executions page — composition only.
 *
 * Mirrors the Sessions page: heading + connection indicator, search, status
 * filter chips + time-window picker, dense table on desktop / card list on
 * mobile. Data fetching, SSE handling, polling fallback, and
 * refetch-while-running all live in the page-level hook.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { Activity } from 'lucide-react'
import { useMemo } from 'react'
import {
  Card,
  EmptyState,
  ListPageHeader,
  ListPagination,
  ListToolbar,
  ResourceFilterBar,
} from '../../components'
import { useExecutionList } from '../../hooks/useExecutionList'
import { useIsMobile } from '../../hooks/useMediaQuery'
import { useRowSelection } from '../../hooks/useRowSelection'
import { formatExecutionIds, formatExecutionsForAgent } from '../../utils/executionExport'
import { ExecutionCardList } from './ExecutionCardList'
import { ExecutionTable } from './ExecutionTable'

function ExecutionEmptyState({ searchQuery }: { searchQuery: string }) {
  return (
    <Card>
      <EmptyState
        icon={Activity}
        title={searchQuery ? 'No matching executions' : 'No executions yet'}
        description={
          searchQuery
            ? 'Try adjusting your search query'
            : 'Executions will appear here when workflows are run'
        }
      />
    </Card>
  )
}

export function ExecutionList() {
  const {
    executions,
    loading,
    searchQuery,
    setSearchQuery,
    selectedStatuses,
    toggleStatus,
    timeWindow,
    setTimeWindow,
    resetView,
    isDefaultView,
    statusCounts,
    sort,
    toggleSort,
    connected,
    lastEventAt,
    page,
    pageSize,
    total,
    excludedUndated,
    setPage,
  } = useExecutionList()

  // Stable identity for useRowSelection: a new array reference each render would
  // trip the items-changed branch and cascade into a render loop.
  const selectionItems = useMemo(
    () => executions.map((e) => ({ ...e, id: e.workflow_execution_id })),
    [executions],
  )
  const selection = useRowSelection(selectionItems)
  const isMobile = useIsMobile()
  const emptyState = <ExecutionEmptyState searchQuery={searchQuery} />

  return (
    <div className="space-y-6">
      <ListPageHeader
        title="Executions"
        description="Workflow runs across all workflows"
        connected={connected}
        lastEventAt={lastEventAt}
      />

      <ListToolbar
        searchPlaceholder="Search executions..."
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        selection={{
          selectedCount: selection.selectedCount,
          onCopyIds: () =>
            formatExecutionIds(selection.selectedItems.map((e) => e.workflow_execution_id)),
          onCopyForAgent: () => formatExecutionsForAgent(selection.selectedItems),
          onClearSelection: selection.clear,
          resourceLabel: 'execution',
        }}
      />

      <ResourceFilterBar
        selectedStatuses={selectedStatuses}
        toggleStatus={toggleStatus}
        statusCounts={statusCounts}
        timeWindow={timeWindow}
        setTimeWindow={setTimeWindow}
        reset={resetView}
        isDefault={isDefaultView}
      />

      {isMobile ? (
        <ExecutionCardList
          rows={executions}
          loading={loading}
          emptyState={emptyState}
          selection={selection.tableProps}
        />
      ) : (
        <ExecutionTable
          rows={executions}
          loading={loading}
          emptyState={emptyState}
          selection={selection.tableProps}
          sort={{ state: sort, onToggle: toggleSort }}
        />
      )}

      <ListPagination
        page={page}
        pageSize={pageSize}
        total={total}
        excludedUndated={excludedUndated}
        onPageChange={setPage}
        itemLabel="execution"
      />
    </div>
  )
}
