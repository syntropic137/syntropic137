import { AlertCircle, Loader2, Pause, Play, Search, Trash2, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  deleteTrigger,
  listTriggers,
  updateTrigger,
  type TriggerSummary,
} from '../api/client'
import { Card, CardContent, EmptyState, PageLoader } from '../components'

const statusColors: Record<string, string> = {
  active: 'bg-green-500/10 text-green-400',
  paused: 'bg-yellow-500/10 text-yellow-400',
  deleted: 'bg-red-500/10 text-red-400',
}

export function TriggerList() {
  const [triggers, setTriggers] = useState<TriggerSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set())

  const fetchTriggers = (showLoader = true) => {
    if (showLoader) setLoading(true)
    setError(null)
    listTriggers({ status: statusFilter || undefined })
      .then((data) => {
        setTriggers(data.triggers)
        setLoading(false)
      })
      .catch((err) => {
        console.error(err)
        setError(err instanceof Error ? err.message : 'Failed to load triggers')
        setLoading(false)
      })
  }

  useEffect(() => {
    fetchTriggers()
  }, [statusFilter])

  const handleToggle = async (trigger: TriggerSummary) => {
    const action = trigger.status === 'active' ? 'pause' : 'resume'
    const newStatus = action === 'pause' ? 'paused' : 'active'
    setActionError(null)
    setBusyIds((prev) => new Set(prev).add(trigger.trigger_id))

    // Optimistic update
    setTriggers((prev) =>
      prev.map((t) =>
        t.trigger_id === trigger.trigger_id ? { ...t, status: newStatus } : t
      )
    )

    try {
      await updateTrigger(trigger.trigger_id, action)
      fetchTriggers(false)
    } catch (err) {
      // Revert optimistic update
      setTriggers((prev) =>
        prev.map((t) =>
          t.trigger_id === trigger.trigger_id ? { ...t, status: trigger.status } : t
        )
      )
      const msg = err instanceof Error ? err.message : `Failed to ${action} trigger`
      setActionError(msg)
      console.error(`Failed to ${action} trigger:`, err)
    } finally {
      setBusyIds((prev) => {
        const next = new Set(prev)
        next.delete(trigger.trigger_id)
        return next
      })
    }
  }

  const handleDelete = async (triggerId: string) => {
    if (!confirm('Delete this trigger?')) return
    setActionError(null)
    setBusyIds((prev) => new Set(prev).add(triggerId))

    // Optimistic update — mark as deleted
    setTriggers((prev) =>
      prev.map((t) =>
        t.trigger_id === triggerId ? { ...t, status: 'deleted' } : t
      )
    )

    try {
      await deleteTrigger(triggerId)
      // Remove from list after successful delete
      setTriggers((prev) => prev.filter((t) => t.trigger_id !== triggerId))
    } catch (err) {
      // Revert
      fetchTriggers(false)
      const msg = err instanceof Error ? err.message : 'Failed to delete trigger'
      setActionError(msg)
      console.error('Failed to delete trigger:', err)
    } finally {
      setBusyIds((prev) => {
        const next = new Set(prev)
        next.delete(triggerId)
        return next
      })
    }
  }

  const filteredTriggers = searchQuery
    ? triggers.filter(
        (t) =>
          t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          t.repository.toLowerCase().includes(searchQuery.toLowerCase()) ||
          t.event.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : triggers

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Triggers</h1>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
          GitHub webhook trigger rules that automatically start workflows
        </p>
      </div>

      {/* Error banner */}
      {(error || actionError) && (
        <div className="flex items-center gap-2 rounded-md border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error || actionError}</span>
          <button
            type="button"
            onClick={() => { setError(null); setActionError(null) }}
            className="ml-auto text-xs hover:text-red-300"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-muted)]" />
          <input
            type="text"
            placeholder="Search triggers..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] py-2 pl-10 pr-4 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)] focus:outline-none"
          />
        </div>

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-primary)]"
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="paused">Paused</option>
        </select>
      </div>

      {/* Content */}
      {loading ? (
        <PageLoader />
      ) : filteredTriggers.length === 0 ? (
        <EmptyState
          title="No triggers found"
          description="Create a trigger to automatically start workflows on GitHub events"
          icon={<Zap className="h-12 w-12 text-[var(--color-text-muted)]" />}
        />
      ) : (
        <div className="space-y-2">
          {filteredTriggers.map((trigger) => {
            const isBusy = busyIds.has(trigger.trigger_id)
            return (
              <Card key={trigger.trigger_id}>
                <CardContent className="flex items-center gap-4 py-3">
                  <Link
                    to={`/triggers/${trigger.trigger_id}`}
                    className="flex min-w-0 flex-1 items-center gap-4 hover:opacity-80 transition-opacity"
                  >
                    {/* Icon */}
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--color-surface-elevated)]">
                      <Zap className="h-4 w-4 text-[var(--color-accent)]" />
                    </div>

                    {/* Info */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-[var(--color-text-primary)]">
                          {trigger.name}
                        </span>
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium transition-colors ${
                            statusColors[trigger.status] ?? 'bg-gray-500/10 text-gray-400'
                          }`}
                        >
                          {trigger.status}
                        </span>
                      </div>
                      <div className="mt-0.5 flex items-center gap-3 text-xs text-[var(--color-text-secondary)]">
                        <span>Event: {trigger.event}</span>
                        {trigger.repository && <span>Repo: {trigger.repository}</span>}
                        <span>Fired: {trigger.fire_count}x</span>
                      </div>
                    </div>
                  </Link>

                  {/* Actions */}
                  <div className="flex items-center gap-1">
                    {trigger.status !== 'deleted' && (
                      <button
                        type="button"
                        onClick={() => handleToggle(trigger)}
                        disabled={isBusy}
                        className="rounded p-1.5 text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-elevated)] hover:text-[var(--color-text-primary)] disabled:opacity-50"
                        title={trigger.status === 'active' ? 'Pause' : 'Resume'}
                      >
                        {isBusy ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : trigger.status === 'active' ? (
                          <Pause className="h-4 w-4" />
                        ) : (
                          <Play className="h-4 w-4" />
                        )}
                      </button>
                    )}
                    {trigger.status !== 'deleted' && (
                      <button
                        type="button"
                        onClick={() => handleDelete(trigger.trigger_id)}
                        disabled={isBusy}
                        className="rounded p-1.5 text-[var(--color-text-secondary)] hover:bg-red-500/10 hover:text-red-400 disabled:opacity-50"
                        title="Delete"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
