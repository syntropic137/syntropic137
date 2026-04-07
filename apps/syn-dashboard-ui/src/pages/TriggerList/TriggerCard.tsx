import { Loader2, Pause, Play, Trash2, Zap } from 'lucide-react'
import { Link } from 'react-router-dom'

import type { TriggerSummary } from '../../api/triggers'
import { Card, CardContent } from '../../components'

const statusColors: Record<string, string> = {
  active: 'bg-green-500/10 text-green-400',
  paused: 'bg-yellow-500/10 text-yellow-400',
  deleted: 'bg-red-500/10 text-red-400',
}

interface TriggerCardProps {
  trigger: TriggerSummary
  isBusy: boolean
  onToggle: (trigger: TriggerSummary) => void
  onDelete: (triggerId: string) => void
}

export function TriggerCard({ trigger, isBusy, onToggle, onDelete }: TriggerCardProps) {
  return (
    <Card>
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
                {trigger.workflow_name ? `${trigger.event} → ${trigger.workflow_name}` : trigger.name}
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
              onClick={() => onToggle(trigger)}
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
              onClick={() => onDelete(trigger.trigger_id)}
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
}
