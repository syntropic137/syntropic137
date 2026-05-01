/**
 * Generic mobile card list — pairs with ResourceTable for narrow viewports.
 *
 * Pages provide a `renderCard(row)` that returns the card body; this primitive
 * owns the outer wrapper, selection checkbox, and tap-to-detail behaviour so
 * Sessions and Executions don't reinvent that scaffolding.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import type { ReactNode } from 'react'
import { clsx } from 'clsx'
import { PageLoader, SelectionCheckbox } from '..'
import type { SelectionProps } from './types'

export interface ResourceCardListProps<Row> {
  rows: Row[]
  loading: boolean
  emptyState: ReactNode
  getRowId: (row: Row) => string
  renderCard: (row: Row) => ReactNode
  onRowClick?: (row: Row) => void
  selection?: SelectionProps
}

interface CardWrapperProps {
  rowId: string
  isSelected: boolean
  onToggleSelection?: (modifiers: { shift: boolean; meta: boolean }) => void
  onClick?: () => void
  children: ReactNode
}

function cardKeyHandler(onClick: (() => void) | undefined): (e: React.KeyboardEvent) => void {
  return (e) => {
    if (!onClick) return
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onClick()
    }
  }
}

interface CardSelectionProps {
  rowId: string
  isSelected: boolean
  onToggle: (modifiers: { shift: boolean; meta: boolean }) => void
}

function CardSelection({ rowId, isSelected, onToggle }: CardSelectionProps) {
  return (
    <div onClick={(e) => e.stopPropagation()} className="pt-0.5">
      <SelectionCheckbox
        checked={isSelected}
        ariaLabel={isSelected ? `Deselect ${rowId}` : `Select ${rowId}`}
        onChange={(e) => onToggle({ shift: e.shiftKey, meta: e.metaKey || e.ctrlKey })}
      />
    </div>
  )
}

function CardWrapper({ rowId, isSelected, onToggleSelection, onClick, children }: CardWrapperProps) {
  return (
    <div
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : -1}
      onClick={onClick}
      onKeyDown={cardKeyHandler(onClick)}
      className={clsx(
        'flex items-start gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 transition-colors hover:bg-[var(--color-surface-elevated)] focus:bg-[var(--color-surface-elevated)] focus:outline-none',
        onClick && 'cursor-pointer',
        isSelected && 'border-[var(--color-accent)] bg-[var(--color-accent)]/10',
      )}
    >
      {onToggleSelection && (
        <CardSelection rowId={rowId} isSelected={isSelected} onToggle={onToggleSelection} />
      )}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

export function ResourceCardList<Row>({
  rows,
  loading,
  emptyState,
  getRowId,
  renderCard,
  onRowClick,
  selection,
}: ResourceCardListProps<Row>) {
  if (loading) return <PageLoader />
  if (rows.length === 0) return <>{emptyState}</>

  return (
    <div className="space-y-3">
      {rows.map((row) => {
        const id = getRowId(row)
        return (
          <CardWrapper
            key={id}
            rowId={id}
            isSelected={selection?.selectedIds.has(id) ?? false}
            onToggleSelection={
              selection ? (mods) => selection.onToggleRow(id, mods) : undefined
            }
            onClick={onRowClick ? () => onRowClick(row) : undefined}
          >
            {renderCard(row)}
          </CardWrapper>
        )
      })}
    </div>
  )
}
