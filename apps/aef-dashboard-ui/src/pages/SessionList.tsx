import { Activity, ChevronRight, Clock, Coins, Search, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { listSessions } from '../api/client'
import { Card, CardContent, EmptyState, PageLoader, StatusBadge } from '../components'
import type { SessionSummary } from '../types'

function formatDuration(startedAt: string | null, completedAt: string | null): string {
  if (!startedAt) return '-'
  const start = new Date(startedAt)
  const end = completedAt ? new Date(completedAt) : new Date()
  const seconds = Math.floor((end.getTime() - start.getTime()) / 1000)
  
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

export function SessionList() {
  const [searchParams] = useSearchParams()
  const workflowIdFilter = searchParams.get('workflow_id') ?? ''
  
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  useEffect(() => {
    let cancelled = false
    listSessions({
      workflow_id: workflowIdFilter || undefined,
      status: statusFilter || undefined,
      limit: 100,
    })
      .then((data) => { if (!cancelled) { setSessions(data); setLoading(false) } })
      .catch((err) => { if (!cancelled) { console.error(err); setLoading(false) } })
    return () => { cancelled = true }
  }, [workflowIdFilter, statusFilter])

  const filteredSessions = searchQuery
    ? sessions.filter((s) =>
        s.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.workflow_id?.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : sessions

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Sessions</h1>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
          Agent sessions across all workflows
        </p>
      </div>

      {/* Filters */}
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

      {/* Session list */}
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
            <Link
              key={session.id}
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
                        <span className="font-mono text-sm font-medium text-[var(--color-text-primary)]">
                          {session.id.slice(0, 12)}...
                        </span>
                        <StatusBadge status={session.status} size="sm" />
                      </div>
                      <div className="mt-0.5 flex items-center gap-3 text-xs text-[var(--color-text-secondary)]">
                        {session.workflow_id && (
                          <>
                            <span>wf:{session.workflow_id.slice(0, 8)}</span>
                            <span>•</span>
                          </>
                        )}
                        {session.phase_id && (
                          <>
                            <span>{session.phase_id}</span>
                            <span>•</span>
                          </>
                        )}
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
                        <span>${session.total_cost_usd.toFixed(4)}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <Clock className="h-3.5 w-3.5" />
                        <span>{formatDuration(session.started_at, session.completed_at)}</span>
                      </div>
                    </div>
                    <ChevronRight className="h-5 w-5 text-[var(--color-text-muted)]" />
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

