/**
 * Sticky action bar for the SessionList multi-select feature.
 *
 * Shown only when at least one row is selected. Renders:
 *   - selection count
 *   - Copy IDs (space-separated, shell-friendly)
 *   - Copy for Claude (markdown table + CLI snippets)
 *   - Clear
 *
 * Mobile: full-width sticky at the bottom of the page content; desktop: same
 * sticky position with comfortable horizontal padding. Inline "Copied!"
 * feedback uses the same pattern as the row Copy-ID button.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { Check, Copy, FileText, X } from 'lucide-react'
import { useCallback } from 'react'
import { clsx } from 'clsx'
import type { SessionSummary } from '../../types'
import { formatSessionIds, formatSessionsForClaude } from '../../utils/sessionExport'
import { useCopyFeedback } from './useCopyFeedback'

interface SelectionActionBarProps {
  selectedSessions: SessionSummary[]
  onClear: () => void
}

export function SelectionActionBar({ selectedSessions, onClear }: SelectionActionBarProps) {
  const count = selectedSessions.length
  const { lastCopied, copy } = useCopyFeedback()

  const handleCopyIds = useCallback(
    () => copy('ids', formatSessionIds(selectedSessions.map((s) => s.id))),
    [copy, selectedSessions],
  )
  const handleCopyClaude = useCallback(
    () => copy('claude', formatSessionsForClaude(selectedSessions)),
    [copy, selectedSessions],
  )

  if (count === 0) return null

  return (
    <div
      role="region"
      aria-label="Selection actions"
      className="sticky bottom-4 z-20 mx-auto flex w-full max-w-3xl flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-3 shadow-lg sm:flex-row sm:items-center sm:justify-between"
    >
      <div
        aria-live="polite"
        className="text-sm font-medium text-[var(--color-text-primary)]"
      >
        {count} selected
      </div>
      <div className="flex flex-wrap items-center gap-2 sm:flex-nowrap">
        <ActionButton
          icon={lastCopied === 'ids' ? Check : Copy}
          label={lastCopied === 'ids' ? 'Copied!' : 'Copy IDs'}
          onClick={handleCopyIds}
          highlight={lastCopied === 'ids'}
        />
        <ActionButton
          icon={lastCopied === 'claude' ? Check : FileText}
          label={lastCopied === 'claude' ? 'Copied!' : 'Copy for Claude'}
          onClick={handleCopyClaude}
          highlight={lastCopied === 'claude'}
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
        'inline-flex h-11 items-center gap-1.5 rounded-md border px-3 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:ring-offset-2 focus:ring-offset-[var(--color-background)] md:h-9',
        variantClass,
        highlight && 'border-[var(--color-accent)] text-[var(--color-accent)]',
      )}
    >
      <Icon className="h-4 w-4" />
      <span>{label}</span>
    </button>
  )
}
