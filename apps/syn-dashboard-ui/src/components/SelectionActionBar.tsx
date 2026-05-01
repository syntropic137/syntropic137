/**
 * Inline selection action bar shared by Sessions and Executions.
 *
 * Renders only when at least one row is selected. Sits in the page's
 * normal flow (above the filter chips) so the actions are visible
 * regardless of how long the list is — no sticky-footer that gets lost
 * when scrolling 100+ rows.
 *
 * The page provides the formatting functions; this component owns the
 * count display, copy-feedback state, and button chrome.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { Check, Copy, FileText, X } from 'lucide-react'
import { useCallback } from 'react'
import { clsx } from 'clsx'
import { useCopyFeedback } from '../hooks/useCopyFeedback'

type CopyKind = 'ids' | 'agent'

export interface SelectionActionBarProps {
  count: number
  onCopyIds: () => string
  onCopyForAgent: () => string
  onClear: () => void
  /** Optional resource label, e.g. "session". Defaults to "selected". */
  resourceLabel?: string
}

export function SelectionActionBar({
  count,
  onCopyIds,
  onCopyForAgent,
  onClear,
  resourceLabel,
}: SelectionActionBarProps) {
  const { lastCopied, copy } = useCopyFeedback<CopyKind>()

  const handleCopyIds = useCallback(() => {
    void copy('ids', onCopyIds())
  }, [copy, onCopyIds])

  const handleCopyForAgent = useCallback(() => {
    void copy('agent', onCopyForAgent())
  }, [copy, onCopyForAgent])

  if (count === 0) return null

  const label = resourceLabel
    ? `${count} ${resourceLabel}${count === 1 ? '' : 's'} selected`
    : `${count} selected`

  return (
    <div
      role="region"
      aria-label="Selection actions"
      className="flex h-10 items-center gap-3 rounded-lg border border-[var(--color-accent)]/40 bg-[var(--color-accent)]/5 px-3"
    >
      <div
        aria-live="polite"
        className="whitespace-nowrap text-sm font-medium text-[var(--color-text-primary)]"
      >
        {label}
      </div>
      <div className="ml-auto flex items-center gap-2">
        <ActionButton
          icon={lastCopied === 'ids' ? Check : Copy}
          label={lastCopied === 'ids' ? 'Copied!' : 'Copy IDs'}
          onClick={handleCopyIds}
          highlight={lastCopied === 'ids'}
        />
        <ActionButton
          icon={lastCopied === 'agent' ? Check : FileText}
          label={lastCopied === 'agent' ? 'Copied!' : 'Copy for Agent'}
          onClick={handleCopyForAgent}
          highlight={lastCopied === 'agent'}
        />
        <ActionButton icon={X} label="Clear" onClick={onClear} variant="ghost" />
      </div>
    </div>
  )
}

interface ActionButtonProps {
  icon: React.ComponentType<{ className?: string }>
  label: string
  onClick: () => void
  highlight?: boolean
  variant?: 'solid' | 'ghost'
}

function ActionButton({
  icon: Icon,
  label,
  onClick,
  highlight = false,
  variant = 'solid',
}: ActionButtonProps) {
  const variantClass =
    variant === 'solid'
      ? 'border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-primary)] hover:border-[var(--color-text-muted)]'
      : 'border-transparent text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:ring-offset-2 focus:ring-offset-[var(--color-background)]',
        variantClass,
        highlight && 'border-[var(--color-accent)] text-[var(--color-accent)]',
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      <span>{label}</span>
    </button>
  )
}
