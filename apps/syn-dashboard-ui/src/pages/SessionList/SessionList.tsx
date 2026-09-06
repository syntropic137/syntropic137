/**
 * Sessions page — composition only.
 *
 * Owns the page layout (heading, filter bar, connection indicator, content
 * slot, sticky action bar). Data fetching, SSE handling, and polling fallback
 * live in the hook; selection state lives in useRowSelection; formatting lives
 * in components and utils.
 *
 * Keyboard shortcuts:
 *   - Cmd/Ctrl+A selects all visible sessions
 *   - Esc clears selection
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { Activity } from 'lucide-react'
import {
  Card,
  EmptyState,
  ListPageHeader,
  ListPagination,
  ListToolbar,
  ResourceFilterBar,
} from '../../components'
import { useIsMobile } from '../../hooks/useMediaQuery'
import { useRowSelection } from '../../hooks/useRowSelection'
import { useSessionList } from '../../hooks/useSessionList'
import { formatSessionIds, formatSessionsForAgent } from '../../utils/sessionExport'
import { SessionCardList } from './SessionCardList'
import { SessionTable } from './SessionTable'
import { useSelectionShortcuts } from './useSelectionShortcuts'

function SessionEmptyState({ searchQuery }: { searchQuery: string }) {
  return (
    <Card>
      <EmptyState
        icon={Activity}
        title={searchQuery ? 'No matching sessions' : 'No sessions yet'}
        description={
          searchQuery
            ? 'Try adjusting your search query'
            : 'Sessions will appear here when workflows are executed'
        }
      />
    </Card>
  )
}

export function SessionList() {
  const {
    sessions,
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
  } = useSessionList()

  const selection = useRowSelection(sessions)
  const isMobile = useIsMobile()

  useSelectionShortcuts({
    selectAll: selection.selectAll,
    clear: selection.clear,
    hasSelection: selection.selectedCount > 0,
  })

  const emptyState = <SessionEmptyState searchQuery={searchQuery} />

  return (
    <div className="space-y-6">
      <ListPageHeader
        title="Sessions"
        description="Agent sessions across all workflows"
        connected={connected}
        lastEventAt={lastEventAt}
      />

      <ListToolbar
        searchPlaceholder="Search sessions..."
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        selection={{
          selectedCount: selection.selectedCount,
          onCopyIds: () => formatSessionIds(selection.selectedItems.map((s) => s.id)),
          onCopyForAgent: () => formatSessionsForAgent(selection.selectedItems),
          onClearSelection: selection.clear,
          resourceLabel: 'session',
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
        <SessionCardList
          rows={sessions}
          loading={loading}
          selection={selection.tableProps}
          emptyState={emptyState}
        />
      ) : (
        <SessionTable
          rows={sessions}
          loading={loading}
          selection={selection.tableProps}
          emptyState={emptyState}
          sort={{ state: sort, onToggle: toggleSort }}
        />
      )}

      <ListPagination
        page={page}
        pageSize={pageSize}
        total={total}
        excludedUndated={excludedUndated}
        onPageChange={setPage}
        itemLabel="session"
      />
    </div>
  )
}
