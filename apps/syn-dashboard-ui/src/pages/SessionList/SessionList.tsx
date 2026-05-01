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

import { Activity, Search } from 'lucide-react'
import {
  Card,
  ConnectionIndicator,
  EmptyState,
  ResourceFilterBar,
  SelectionActionBar,
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

interface SessionSearchBarProps {
  value: string
  onChange: (value: string) => void
}

function SessionSearchBar({ value, onChange }: SessionSearchBarProps) {
  return (
    <div className="relative w-full sm:max-w-md">
      <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-muted)]" />
      <input
        type="text"
        placeholder="Search sessions..."
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] py-2.5 pl-10 pr-4 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)] md:py-2"
      />
    </div>
  )
}

export function SessionList() {
  const {
    filteredSessions,
    loading,
    searchQuery,
    setSearchQuery,
    selectedStatuses,
    toggleStatus,
    timeWindow,
    setTimeWindow,
    clearAllFilters,
    statusCounts,
    sort,
    toggleSort,
    connected,
    lastEventAt,
  } = useSessionList()

  const selection = useRowSelection(filteredSessions)
  const isMobile = useIsMobile()

  useSelectionShortcuts({
    selectAll: selection.selectAll,
    clear: selection.clear,
    hasSelection: selection.selectedCount > 0,
  })

  const selectionProps = {
    selectedIds: selection.selectedIds,
    onToggleRow: selection.handleClick,
    onSelectAll: selection.selectAll,
    onClearSelection: selection.clear,
  }
  const emptyState = <SessionEmptyState searchQuery={searchQuery} />

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Sessions</h1>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            Agent sessions across all workflows
          </p>
        </div>
        <ConnectionIndicator connected={connected} lastEventAt={lastEventAt} />
      </div>

      <SessionSearchBar value={searchQuery} onChange={setSearchQuery} />

      <SelectionActionBar
        count={selection.selectedCount}
        onCopyIds={() => formatSessionIds(selection.selectedItems.map((s) => s.id))}
        onCopyForAgent={() => formatSessionsForAgent(selection.selectedItems)}
        onClear={selection.clear}
        resourceLabel="session"
      />

      <ResourceFilterBar
        selectedStatuses={selectedStatuses}
        toggleStatus={toggleStatus}
        statusCounts={statusCounts}
        timeWindow={timeWindow}
        setTimeWindow={setTimeWindow}
        clearAll={clearAllFilters}
      />

      {isMobile ? (
        <SessionCardList
          rows={filteredSessions}
          loading={loading}
          selection={selectionProps}
          emptyState={emptyState}
        />
      ) : (
        <SessionTable
          rows={filteredSessions}
          loading={loading}
          selection={selectionProps}
          emptyState={emptyState}
          sort={{ state: sort, onToggle: toggleSort }}
        />
      )}
    </div>
  )
}
