/**
 * Sessions page — composition only.
 *
 * Owns the page layout (heading, filter bar, connection indicator, content
 * slot). Data fetching, SSE handling, and polling fallback live in the hook;
 * formatting lives in components and utils.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { Activity, Search } from 'lucide-react'
import { Card, ConnectionIndicator, EmptyState } from '../../components'
import { useSessionList } from '../../hooks/useSessionList'
import { SessionTable } from './SessionTable'

export function SessionList() {
  const {
    filteredSessions,
    loading,
    searchQuery,
    setSearchQuery,
    statusFilter,
    setStatusFilter,
    connected,
    lastEventAt,
  } = useSessionList()

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Sessions</h1>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            Agent sessions across all workflows
          </p>
        </div>
        <ConnectionIndicator connected={connected} lastEventAt={lastEventAt} />
      </div>

      <div className="flex items-center gap-4">
        <div className="relative max-w-md flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-muted)]" />
          <input
            type="text"
            placeholder="Search sessions..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] py-2 pl-10 pr-4 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]"
        >
          <option value="">All statuses</option>
          <option value="pending">Pending</option>
          <option value="running">Running</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      <SessionTable
        rows={filteredSessions}
        loading={loading}
        emptyState={
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
        }
      />
    </div>
  )
}
