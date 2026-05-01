/**
 * Status + time-window filter bar shared by Sessions and Executions.
 *
 * Composes status FilterChips + TimeWindowPicker + a Clear-all link. Pure
 * presentational — receives state and handlers from the page-level hook.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { FilterChip } from './FilterChip'
import { TimeWindowPicker } from './TimeWindowPicker'
import type { TimeWindow } from '../types'

export interface ResourceFilterBarProps {
  selectedStatuses: Set<string>
  toggleStatus: (status: string) => void
  statusCounts: Record<string, number>
  timeWindow: TimeWindow
  setTimeWindow: (next: TimeWindow) => void
  /** Restore default filters + sort; surfaces the Reset button when truthy. */
  reset: () => void
  /** When false (defaults are active), the Reset button is hidden. */
  isDefault: boolean
}

const STATUSES: { value: string; label: string }[] = [
  { value: 'pending', label: 'Pending' },
  { value: 'running', label: 'Running' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
]

export function ResourceFilterBar({
  selectedStatuses,
  toggleStatus,
  statusCounts,
  timeWindow,
  setTimeWindow,
  reset,
  isDefault,
}: ResourceFilterBarProps) {
  return (
    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div className="flex flex-wrap items-center gap-2">
        {STATUSES.map((s) => (
          <FilterChip
            key={s.value}
            label={s.label}
            count={statusCounts[s.value] ?? 0}
            isActive={selectedStatuses.has(s.value)}
            onClick={() => toggleStatus(s.value)}
          />
        ))}
      </div>
      <div className="flex items-center gap-3">
        {!isDefault && (
          <button
            type="button"
            onClick={reset}
            className="text-xs text-[var(--color-text-secondary)] underline-offset-2 hover:text-[var(--color-text-primary)] hover:underline"
          >
            Reset
          </button>
        )}
        <TimeWindowPicker value={timeWindow} onChange={setTimeWindow} />
      </div>
    </div>
  )
}
