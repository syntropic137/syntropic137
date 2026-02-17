import {
  Activity,
  Clock,
  ExternalLink,
  GitBranch,
  Hash,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import {
  getTrigger,
  getTriggerHistory,
  type TriggerDetail as TriggerDetailType,
  type TriggerHistoryEntry,
} from '../api/client'
import {
  Breadcrumbs,
  Card,
  CardContent,
  CardHeader,
  EmptyState,
  MetricCard,
  PageLoader,
  StatusBadge,
} from '../components'

const statusColors: Record<string, string> = {
  active: 'bg-green-500/10 text-green-400 ring-green-500/30',
  paused: 'bg-yellow-500/10 text-yellow-400 ring-yellow-500/30',
  deleted: 'bg-red-500/10 text-red-400 ring-red-500/30',
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return '—'
  const d = new Date(ts)
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function JsonBlock({ data }: { data: Record<string, unknown> | null }) {
  if (!data || Object.keys(data).length === 0) {
    return <span className="text-sm text-[var(--color-text-muted)]">None</span>
  }
  return (
    <pre className="overflow-x-auto rounded-md bg-[var(--color-surface-elevated)] p-3 text-xs text-[var(--color-text-secondary)]">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}

export function TriggerDetail() {
  const { triggerId } = useParams<{ triggerId: string }>()
  const navigate = useNavigate()
  const [trigger, setTrigger] = useState<TriggerDetailType | null>(null)
  const [history, setHistory] = useState<TriggerHistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!triggerId) return

    let cancelled = false
    Promise.all([getTrigger(triggerId), getTriggerHistory(triggerId)])
      .then(([t, h]) => {
        if (cancelled) return
        setTrigger(t)
        setHistory(h.entries)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load trigger')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [triggerId])

  if (loading) return <PageLoader />

  if (error || !trigger) {
    return (
      <Card>
        <EmptyState
          icon={Zap}
          title="Trigger not found"
          description={error || `Could not find trigger with ID: ${triggerId}`}
          action={{ label: 'Back to Triggers', onClick: () => navigate('/triggers') }}
        />
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumbs */}
      <Breadcrumbs
        items={[
          { label: 'Triggers', href: '/triggers' },
          { label: trigger.name },
        ]}
      />

      {/* Header */}
      <div className="flex items-start gap-4">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20">
          <Zap className="h-6 w-6 text-amber-400" />
        </div>
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">
              {trigger.name}
            </h1>
            <span
              className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-medium ring-1 ring-inset ${
                statusColors[trigger.status] ?? 'bg-gray-500/10 text-gray-400 ring-gray-500/30'
              }`}
            >
              {trigger.status}
            </span>
          </div>
          <div className="mt-2 flex items-center gap-4 text-xs text-[var(--color-text-muted)]">
            <span className="font-mono">{trigger.trigger_id}</span>
            <span>Event: {trigger.event}</span>
            {trigger.repository && (
              <>
                <span>•</span>
                <span>{trigger.repository}</span>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Fire Count"
          value={trigger.fire_count}
          icon={Activity}
          color="accent"
        />
        <MetricCard
          title="Event Type"
          value={trigger.event}
          icon={Zap}
        />
        <MetricCard
          title="Repository"
          value={trigger.repository || '—'}
          icon={GitBranch}
        />
        <MetricCard
          title="Workflow"
          value={trigger.workflow_id.slice(0, 12) + '...'}
          icon={ExternalLink}
          href={`/workflows/${trigger.workflow_id}`}
          subtitle="View workflow →"
        />
      </div>

      {/* Configuration */}
      <Card>
        <CardHeader title="Configuration" subtitle="Trigger conditions, input mapping, and config" />
        <CardContent>
          <div className="space-y-4">
            <div>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wider text-[var(--color-text-secondary)]">
                Conditions
              </h3>
              <JsonBlock data={trigger.conditions} />
            </div>
            <div>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wider text-[var(--color-text-secondary)]">
                Input Mapping
              </h3>
              <JsonBlock data={trigger.input_mapping} />
            </div>
            <div>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wider text-[var(--color-text-secondary)]">
                Config
              </h3>
              <JsonBlock data={trigger.config} />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Firing History */}
      <Card>
        <CardHeader
          title="Firing History"
          subtitle={`${history.length} event${history.length !== 1 ? 's' : ''}`}
        />
        <CardContent noPadding>
          {history.length === 0 ? (
            <div className="p-8 text-center">
              <Clock className="mx-auto h-8 w-8 text-[var(--color-text-muted)]" />
              <p className="mt-2 text-sm text-[var(--color-text-muted)]">
                No firing events yet
              </p>
            </div>
          ) : (
            <div className="divide-y divide-[var(--color-border)]">
              {history.map((entry, idx) => (
                <div
                  key={entry.execution_id ?? idx}
                  className="flex items-center justify-between px-4 py-3"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-surface-elevated)]">
                      <Zap className="h-4 w-4 text-[var(--color-text-secondary)]" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-[var(--color-text-primary)]">
                          {entry.event_type || 'unknown'}
                        </span>
                        {entry.status && <StatusBadge status={entry.status} size="sm" />}
                      </div>
                      <div className="mt-0.5 flex items-center gap-3 text-xs text-[var(--color-text-muted)]">
                        <span>{formatTimestamp(entry.fired_at)}</span>
                        {entry.pr_number != null && (
                          <span className="flex items-center gap-1">
                            <Hash className="h-3 w-3" />
                            PR {entry.pr_number}
                          </span>
                        )}
                        {entry.cost_usd != null && (
                          <span>${Number(entry.cost_usd).toFixed(4)}</span>
                        )}
                      </div>
                    </div>
                  </div>
                  {entry.execution_id && (
                    <Link
                      to={`/executions/${entry.execution_id}`}
                      className="text-xs text-[var(--color-accent)] hover:underline"
                    >
                      View execution →
                    </Link>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
