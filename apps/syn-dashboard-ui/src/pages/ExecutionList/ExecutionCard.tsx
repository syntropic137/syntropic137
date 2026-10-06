/**
 * Mobile card content for a single execution.
 *
 * Pure presentation: renders the inner header row + metric grid. The outer
 * card wrapper, hover/focus state, and link-to-detail navigation are owned
 * by ResourceCardList.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { CardMetric, StatusBadge } from '../../components'
import type { ExecutionListItem } from '../../types'
import { formatRelativeTime, formatTimestampLocale } from '../../utils/formatters'

const EM_DASH = '—'

export function ExecutionCard({ exec }: { exec: ExecutionListItem }) {
  const workflowLabel = exec.workflow_name || exec.workflow_id
  return (
    <div className="flex flex-col gap-3">
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex items-center gap-2">
          <StatusBadge
            status={exec.status}
            failureClassification={exec.failure_classification}
            size="sm"
          />
          <span
            className="truncate text-sm font-medium text-[var(--color-text-primary)]"
            title={workflowLabel}
          >
            {workflowLabel}
          </span>
        </div>
        <div
          className="text-xs text-[var(--color-text-muted)]"
          title={formatTimestampLocale(exec.started_at) ?? undefined}
        >
          {formatRelativeTime(exec.started_at)}
          {exec.total_phases > 0 && (
            <> &middot; {exec.completed_phases}/{exec.total_phases} phases</>
          )}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <CardMetric wide label="Repos" value={exec.repos_display ?? EM_DASH} />
        <CardMetric label="Tokens" value={exec.total_tokens_display} />
        <CardMetric label="Cost" value={exec.total_cost_display} />
        <CardMetric label="Duration" value={exec.duration_display} />
      </div>
    </div>
  )
}
