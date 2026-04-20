/**
 * Picks a relative time window for filtering session lists.
 *
 * Renders as a segmented button group at md: and up; collapses to a native
 * <select> below md: where horizontal space is tight.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { clsx } from 'clsx'
import type { TimeWindow } from '../types'

interface TimeWindowPickerProps {
  value: TimeWindow
  onChange: (next: TimeWindow) => void
}

interface Option {
  value: TimeWindow
  label: string
  shortLabel: string
}

const OPTIONS: Option[] = [
  { value: '15m', label: 'Last 15 min', shortLabel: '15m' },
  { value: '1h', label: 'Last hour', shortLabel: '1h' },
  { value: '24h', label: 'Last 24 hours', shortLabel: '24h' },
  { value: '7d', label: 'Last 7 days', shortLabel: '7d' },
  { value: 'all', label: 'All time', shortLabel: 'All' },
]

export function TimeWindowPicker({ value, onChange }: TimeWindowPickerProps) {
  return (
    <>
      {/* Mobile: native select for compactness */}
      <select
        aria-label="Time window"
        value={value}
        onChange={(e) => onChange(e.target.value as TimeWindow)}
        className="h-11 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)] md:hidden"
      >
        {OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Desktop: segmented control */}
      <div
        role="radiogroup"
        aria-label="Time window"
        className="hidden h-7 items-center rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-0.5 md:inline-flex"
      >
        {OPTIONS.map((opt) => {
          const active = opt.value === value
          return (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(opt.value)}
              className={clsx(
                'rounded px-2 py-0.5 text-xs font-medium transition-colors focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]',
                active
                  ? 'bg-[var(--color-accent)] text-white'
                  : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]',
              )}
            >
              {opt.shortLabel}
            </button>
          )
        })}
      </div>
    </>
  )
}
