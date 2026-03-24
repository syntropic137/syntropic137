import { Clock, Hash, Zap } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Card, CardContent, CardHeader, StatusBadge } from '../../components'
import type { TriggerHistoryEntry } from '../../api/triggers'
import { formatTimestamp } from '../../utils/formatters'

function HistoryRow({ entry, idx }: { entry: TriggerHistoryEntry; idx: number }) {
  return (
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
          View execution &rarr;
        </Link>
      )}
    </div>
  )
}

export function TriggerFiringHistory({ history }: { history: TriggerHistoryEntry[] }) {
  return (
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
              <HistoryRow key={entry.execution_id ?? idx} entry={entry} idx={idx} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
