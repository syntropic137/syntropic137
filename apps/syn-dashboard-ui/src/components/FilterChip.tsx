/**
 * Toggleable filter pill — used in the Sessions filter bar.
 *
 * Pure presentational. Caller owns the active state. Touch target is 44x44
 * below md: per Apple HIG and Google Material guidelines.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { clsx } from 'clsx'

interface FilterChipProps {
  label: string
  count?: number
  isActive: boolean
  onClick: () => void
  disabled?: boolean
}

export function FilterChip({ label, count, isActive, onClick, disabled = false }: FilterChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={isActive}
      disabled={disabled}
      className={clsx(
        'inline-flex h-11 items-center gap-1.5 rounded-full border px-3 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:ring-offset-2 focus:ring-offset-[var(--color-background)] md:h-7 md:text-xs',
        isActive
          ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/15 text-[var(--color-accent)]'
          : 'border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-secondary)] hover:border-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]',
        disabled && 'cursor-not-allowed opacity-50',
      )}
    >
      <span>{label}</span>
      {count !== undefined && (
        <span
          className={clsx(
            'rounded-full px-1.5 py-0.5 text-[10px] font-mono',
            isActive
              ? 'bg-[var(--color-accent)]/20 text-[var(--color-accent)]'
              : 'bg-[var(--color-surface-elevated)] text-[var(--color-text-muted)]',
          )}
        >
          {count}
        </span>
      )}
    </button>
  )
}
