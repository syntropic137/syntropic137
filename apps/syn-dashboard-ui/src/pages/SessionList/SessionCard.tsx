/**
 * Mobile card content for a single session.
 *
 * Pure presentation: renders the inner header row + metric grid. The outer
 * card wrapper, selection checkbox, hover/focus state, and link-to-detail
 * navigation are owned by ResourceCardList.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { AgentBadge, CardMetric, ObservedModel, StatusBadge } from '../../components'
import type { SessionSummary } from '../../types'
import { formatRelativeTime, formatTimestampLocale } from '../../utils/formatters'

const EM_DASH = '—'

export function SessionCard({ session }: { session: SessionSummary }) {
  const workflowLabel = session.workflow_name ?? session.workflow_id ?? 'Unknown workflow'
  const phaseLabel = session.phase_display ?? session.phase_id
  return (
    <div className="flex flex-col gap-3">
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex items-center gap-2">
          <StatusBadge status={session.status} size="sm" />
          <AgentBadge provider={session.agent_provider} />
          <ObservedModel
            display={session.agent_model_display}
            observed={session.agent_model}
            requested={session.requested_model}
            className="text-xs text-[var(--color-text-secondary)]"
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
          title={formatTimestampLocale(session.started_at) ?? undefined}
        >
          {formatRelativeTime(session.started_at)}
          {phaseLabel && <> &middot; {phaseLabel}</>}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <CardMetric wide label="Repos" value={session.repos_display ?? EM_DASH} />
        <CardMetric label="Tokens" value={session.total_tokens_display} />
        <CardMetric label="Cost" value={session.total_cost_display} />
        <CardMetric label="Duration" value={session.duration_display} />
      </div>
    </div>
  )
}
