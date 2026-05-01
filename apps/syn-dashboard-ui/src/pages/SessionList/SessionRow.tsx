/**
 * Single session row in the SessionList table.
 *
 * Pure presentation: takes one SessionSummary, renders the cells, navigates on
 * click. All heavy formatting (tokens, cost, duration, model) is consumed
 * directly from the API's `*_display` fields; only locale-dependent values
 * (relative time, absolute timestamp) are formatted client-side.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useNavigate } from 'react-router-dom'
import { Copy } from 'lucide-react'
import { useState } from 'react'
import { clsx } from 'clsx'
import { SelectionCheckbox, StatusBadge } from '../../components'
import type { SessionSummary } from '../../types'
import type { SelectionClickModifiers } from '../../hooks/useRowSelection'
import { formatRelativeTime, formatTimestampLocale } from '../../utils/formatters'

interface SessionRowProps {
  session: SessionSummary
  isSelected?: boolean
  onToggleSelection?: (modifiers: SelectionClickModifiers) => void
}

const EM_DASH = '—'

interface DerivedCells {
  workflowLabel: string
  phaseLabel: string
  phaseTitle: string | undefined
  reposLabel: string
  reposTitle: string | undefined
}

function deriveCells(session: SessionSummary): DerivedCells {
  return {
    workflowLabel: session.workflow_name ?? session.workflow_id ?? 'Unknown workflow',
    phaseLabel: session.phase_display ?? session.phase_id ?? EM_DASH,
    phaseTitle: session.phase_id ?? undefined,
    reposLabel: session.repos_display ?? EM_DASH,
    reposTitle: session.repos.join('\n') || undefined,
  }
}

export function SessionRow({
  session,
  isSelected = false,
  onToggleSelection,
}: SessionRowProps) {
  const navigate = useNavigate()
  const [copied, setCopied] = useState(false)
  const cells = deriveCells(session)

  const handleClick = () => {
    navigate(`/sessions/${session.id}`)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      handleClick()
    }
  }

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await navigator.clipboard.writeText(session.id)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch {
      // ignore — clipboard API can fail in older browsers
    }
  }

  return (
    <tr
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      tabIndex={0}
      role="button"
      title={session.id}
      className={clsx(
        'group cursor-pointer border-b border-[var(--color-border)] transition-colors hover:bg-[var(--color-surface-elevated)] focus:bg-[var(--color-surface-elevated)] focus:outline-none',
        isSelected && 'bg-[var(--color-accent)]/10',
      )}
    >
      {onToggleSelection && (
        <td className="w-10 px-3 py-2">
          <SelectionCheckbox
            checked={isSelected}
            ariaLabel={isSelected ? `Deselect session ${session.id}` : `Select session ${session.id}`}
            onChange={(e) =>
              onToggleSelection({ shift: e.shiftKey, meta: e.metaKey || e.ctrlKey })
            }
          />
        </td>
      )}
      <td className="px-3 py-2">
        <StatusBadge status={session.status} size="sm" />
      </td>
      <td className="px-3 py-2 text-sm text-[var(--color-text-primary)]">
        {cells.workflowLabel}
      </td>
      <td
        className="px-3 py-2 text-xs text-[var(--color-text-secondary)]"
        title={cells.phaseTitle}
      >
        {cells.phaseLabel}
      </td>
      <td
        className="px-3 py-2 text-xs text-[var(--color-text-secondary)]"
        title={cells.reposTitle}
      >
        {cells.reposLabel}
      </td>
      <td className="px-3 py-2 text-right font-mono text-xs text-[var(--color-text-secondary)]">
        {session.total_tokens_display}
      </td>
      <td className="px-3 py-2 text-right font-mono text-xs text-[var(--color-text-secondary)]">
        {session.total_cost_display}
      </td>
      <td className="px-3 py-2 text-right font-mono text-xs text-[var(--color-text-secondary)]">
        {session.duration_display}
      </td>
      <td
        className="px-3 py-2 text-xs text-[var(--color-text-secondary)]"
        title={formatTimestampLocale(session.started_at)}
      >
        {formatRelativeTime(session.started_at)}
      </td>
      <td className="px-3 py-2 text-right">
        <button
          type="button"
          onClick={handleCopy}
          aria-label="Copy session id"
          title={copied ? 'Copied!' : 'Copy session id'}
          className="inline-flex h-9 w-9 items-center justify-center rounded text-[var(--color-text-muted)] transition-colors hover:bg-[var(--color-surface)] hover:text-[var(--color-text-primary)] md:invisible md:h-auto md:w-auto md:p-1 md:group-hover:visible"
        >
          <Copy className="h-4 w-4 md:h-3.5 md:w-3.5" />
        </button>
      </td>
    </tr>
  )
}
