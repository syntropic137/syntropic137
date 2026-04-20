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
import { StatusBadge } from '../../components'
import type { SessionSummary } from '../../types'
import { formatRelativeTime, formatTimestampLocale } from '../../utils/formatters'

interface SessionRowProps {
  session: SessionSummary
}

export function SessionRow({ session }: SessionRowProps) {
  const navigate = useNavigate()
  const [copied, setCopied] = useState(false)

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
      className="group cursor-pointer border-b border-[var(--color-border)] transition-colors hover:bg-[var(--color-surface-elevated)] focus:bg-[var(--color-surface-elevated)] focus:outline-none"
    >
      <td className="px-3 py-2">
        <StatusBadge status={session.status} size="sm" />
      </td>
      <td className="px-3 py-2 text-sm text-[var(--color-text-primary)]">
        {session.workflow_name ?? session.workflow_id ?? 'Unknown workflow'}
      </td>
      <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">
        {session.phase_id ?? '\u2014'}
      </td>
      <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">
        {session.agent_model_display ?? '\u2014'}
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
          className="invisible rounded p-1 text-[var(--color-text-muted)] transition-colors hover:bg-[var(--color-surface)] hover:text-[var(--color-text-primary)] group-hover:visible"
        >
          <Copy className="h-3.5 w-3.5" />
        </button>
      </td>
    </tr>
  )
}
