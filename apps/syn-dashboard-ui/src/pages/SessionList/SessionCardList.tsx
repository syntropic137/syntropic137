/**
 * Mobile card-list rendering of sessions.
 *
 * Shares the same data, loading, empty-state, and selection contract as
 * SessionTable so the page can swap between them via useIsMobile().
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import type { ReactNode } from 'react'
import { PageLoader } from '../../components'
import type { SessionSummary } from '../../types'
import type { SelectionClickModifiers } from '../../hooks/useRowSelection'
import { SessionCard } from './SessionCard'

interface SelectionProps {
  selectedIds: Set<string>
  onToggleRow: (id: string, modifiers: SelectionClickModifiers) => void
  onSelectAll: () => void
  onClearSelection: () => void
}

interface SessionCardListProps {
  rows: SessionSummary[]
  loading: boolean
  emptyState: ReactNode
  selection?: SelectionProps
}

export function SessionCardList({ rows, loading, emptyState, selection }: SessionCardListProps) {
  if (loading) return <PageLoader />
  if (rows.length === 0) return <>{emptyState}</>

  return (
    <div className="flex flex-col gap-2">
      {rows.map((session) => (
        <SessionCard
          key={session.id}
          session={session}
          isSelected={selection?.selectedIds.has(session.id) ?? false}
          onToggleSelection={
            selection ? (mods) => selection.onToggleRow(session.id, mods) : undefined
          }
        />
      ))}
    </div>
  )
}
