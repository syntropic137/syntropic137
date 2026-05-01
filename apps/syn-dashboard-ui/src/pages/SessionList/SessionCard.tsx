/**
 * Mobile card presentation of a single session.
 *
 * Used below the `md:` breakpoint where a 9-column table would require
 * horizontal scrolling. Same display fields as SessionRow; entire card
 * is a button that navigates to /sessions/:id, with a leading checkbox
 * that toggles selection without firing the navigation.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useNavigate } from 'react-router-dom'
import { clsx } from 'clsx'
import { SelectionCheckbox, StatusBadge } from '../../components'
import type { SessionSummary } from '../../types'
import type { SelectionClickModifiers } from '../../hooks/useRowSelection'
import { formatRelativeTime, formatTimestampLocale } from '../../utils/formatters'

interface SessionCardProps {
  session: SessionSummary
  isSelected?: boolean
  onToggleSelection?: (modifiers: SelectionClickModifiers) => void
}

function MetricCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-[var(--color-text-muted)]">
        {label}
      </div>
      <div className="font-mono text-xs text-[var(--color-text-primary)]">{value}</div>
    </div>
  )
}

export function SessionCard({
  session,
  isSelected = false,
  onToggleSelection,
}: SessionCardProps) {
  const navigate = useNavigate()
  const handleNavigate = () => navigate(`/sessions/${session.id}`)

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleNavigate}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          handleNavigate()
        }
      }}
      className={clsx(
        'flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3 transition-colors hover:bg-[var(--color-surface-elevated)] focus:bg-[var(--color-surface-elevated)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]',
        isSelected && 'border-[var(--color-accent)] bg-[var(--color-accent)]/10',
      )}
    >
      <div className="flex items-start gap-3">
        {onToggleSelection && (
          <SelectionCheckbox
            checked={isSelected}
            ariaLabel={isSelected ? `Deselect session ${session.id}` : `Select session ${session.id}`}
            onChange={(e) =>
              onToggleSelection({ shift: e.shiftKey, meta: e.metaKey || e.ctrlKey })
            }
            className="mt-1"
          />
        )}
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex items-center gap-2">
            <StatusBadge status={session.status} size="sm" />
            <span className="truncate text-sm font-medium text-[var(--color-text-primary)]" title={session.workflow_name ?? session.workflow_id ?? undefined}>
              {session.workflow_name ?? session.workflow_id ?? 'Unknown workflow'}
            </span>
          </div>
          <div
            className="text-xs text-[var(--color-text-muted)]"
            title={formatTimestampLocale(session.started_at)}
          >
            {formatRelativeTime(session.started_at)}
            {(session.phase_display ?? session.phase_id) && (
              <> &middot; {session.phase_display ?? session.phase_id}</>
            )}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <MetricCell label="Repos" value={session.repos_display ?? '\u2014'} />
        <MetricCell label="Tokens" value={session.total_tokens_display} />
        <MetricCell label="Cost" value={session.total_cost_display} />
        <MetricCell label="Duration" value={session.duration_display} />
      </div>
    </div>
  )
}
