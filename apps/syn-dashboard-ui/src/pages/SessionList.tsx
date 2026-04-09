import { Activity, ChevronRight, Clock, Coins, Search, Zap } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Card, CardContent, EmptyState, PageLoader, StatusBadge } from '../components'
import { useSessionList } from '../hooks/useSessionList'
import type { SessionSummary } from '../types'
import { formatDurationFromRange } from '../utils/formatters'

function SessionRow({ session, idx }: { session: SessionSummary; idx: number }) {
  return (
    <Link
      to={`/sessions/${session.id}`}
      className="block animate-fade-in"
      style={{ animationDelay: `${idx * 20}ms` }}
    >
      <Card hover>
        <CardContent className="flex items-center justify-between py-3">
          <div className="flex items-center gap-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--color-surface-elevated)]">
              <Activity className="h-5 w-5 text-emerald-400" />
            </div>
            <div>
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium text-[var(--color-text-primary)]">
                  {session.workflow_name ?? session.id.slice(0, 12) + '...'}
                </span>
                <StatusBadge status={session.status} size="sm" />
              </div>
              <div className="mt-0.5 flex items-center gap-3 text-xs text-[var(--color-text-secondary)]">
                <span className="font-mono">{session.id.slice(0, 8)}</span>
                {session.phase_id && (
                  <>
                    <span>&bull;</span>
                    <span>{session.phase_id}</span>
                  </>
                )}
                <span>&bull;</span>
                <span>{session.agent_provider ?? 'unknown'}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-4 text-xs text-[var(--color-text-secondary)]">
              <div className="flex items-center gap-1">
                <Zap className="h-3.5 w-3.5" />
                <span>{session.total_tokens.toLocaleString()}</span>
              </div>
              <div className="flex items-center gap-1">
                <Coins className="h-3.5 w-3.5" />
                <span>${Number(session.total_cost_usd).toFixed(4)}</span>
              </div>
              <div className="flex items-center gap-1">
                <Clock className="h-3.5 w-3.5" />
                <span>{formatDurationFromRange(session.started_at, session.completed_at)}</span>
              </div>
            </div>
            <ChevronRight className="h-5 w-5 text-[var(--color-text-muted)]" />
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

export function SessionList() {
  const {
    filteredSessions,
    loading,
    searchQuery,
    setSearchQuery,
    statusFilter,
    setStatusFilter,
  } = useSessionList()

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Sessions</h1>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
          Agent sessions across all workflows
        </p>
      </div>

      <div className="flex items-center gap-4">
        <div className="relative flex-1 max-w-md">
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

      {loading ? (
        <PageLoader />
      ) : filteredSessions.length === 0 ? (
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
      ) : (
        <div className="space-y-2">
          {filteredSessions.map((session, idx) => (
            <SessionRow key={session.id} session={session} idx={idx} />
          ))}
        </div>
      )}
    </div>
  )
}
