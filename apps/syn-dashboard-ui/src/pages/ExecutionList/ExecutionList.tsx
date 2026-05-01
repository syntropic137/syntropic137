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

import { Activity, Search } from 'lucide-react'
import { Card, ConnectionIndicator, EmptyState, ResourceFilterBar } from '../../components'
import { useExecutionList } from '../../hooks/useExecutionList'
import { useIsMobile } from '../../hooks/useMediaQuery'
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

interface ExecutionSearchBarProps {
  value: string
  onChange: (value: string) => void
}

function ExecutionSearchBar({ value, onChange }: ExecutionSearchBarProps) {
  return (
    <div className="relative w-full sm:max-w-md">
      <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-muted)]" />
      <input
        type="text"
        placeholder="Search executions..."
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] py-2.5 pl-10 pr-4 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)] md:py-2"
      />
    </div>
  )
}

export function ExecutionList() {
  const {
    filteredExecutions,
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
  } = useExecutionList()

  const isMobile = useIsMobile()
  const emptyState = <ExecutionEmptyState searchQuery={searchQuery} />

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Executions</h1>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            Workflow runs across all workflows
          </p>
        </div>
        <ConnectionIndicator connected={connected} lastEventAt={lastEventAt} />
      </div>

      <ExecutionSearchBar value={searchQuery} onChange={setSearchQuery} />

      <ResourceFilterBar
        selectedStatuses={selectedStatuses}
        toggleStatus={toggleStatus}
        statusCounts={statusCounts}
        timeWindow={timeWindow}
        setTimeWindow={setTimeWindow}
        clearAll={clearAllFilters}
      />

      {isMobile ? (
        <ExecutionCardList rows={filteredExecutions} loading={loading} emptyState={emptyState} />
      ) : (
        <ExecutionTable
          rows={filteredExecutions}
          loading={loading}
          emptyState={emptyState}
          sort={{ state: sort, onToggle: toggleSort }}
        />
      )}
    </div>
  )
}
