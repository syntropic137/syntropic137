/**
 * The row above a list: search it, and act on what is selected in it.
 *
 * Sessions and Executions each carried a private copy of this - the same
 * input with a different placeholder, and the same action bar behind the same
 * "only while something is selected" condition. Two copies of one thing is
 * exactly how the two lists drifted apart in the first place (#1159), so the
 * condition and the layout are settled here and a page states only its nouns.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { Search } from 'lucide-react'
import { SelectionActionBar } from './SelectionActionBar'

export interface ListToolbarProps {
  searchPlaceholder: string
  searchQuery: string
  onSearchChange: (value: string) => void
  /** The selection actions appear only while this is above zero. */
  selectedCount: number
  /** Returns the text to put on the clipboard. */
  onCopyIds: () => string
  /** Returns the agent-shaped text to put on the clipboard. */
  onCopyForAgent: () => string
  onClearSelection: () => void
  /** Singular noun for the selection count, e.g. "session". */
  resourceLabel: string
}

export function ListToolbar({
  searchPlaceholder,
  searchQuery,
  onSearchChange,
  selectedCount,
  onCopyIds,
  onCopyForAgent,
  onClearSelection,
  resourceLabel,
}: ListToolbarProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
      <div className="relative w-full sm:max-w-md">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-muted)]" />
        <input
          type="text"
          placeholder={searchPlaceholder}
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] py-2.5 pl-10 pr-4 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)] md:py-2"
        />
      </div>
      {selectedCount > 0 && (
        <div className="flex-1">
          <SelectionActionBar
            count={selectedCount}
            onCopyIds={onCopyIds}
            onCopyForAgent={onCopyForAgent}
            onClear={onClearSelection}
            resourceLabel={resourceLabel}
          />
        </div>
      )}
    </div>
  )
}
