/**
 * Presentational table that renders a list of session rows.
 *
 * Pure component: takes already-fetched data plus loading/empty slots and
 * renders the table chrome. No data fetching, no business logic.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import type { ReactNode } from 'react'
import type { SessionSummary } from '../../types'
import { PageLoader, SelectionCheckbox } from '../../components'
import type { SelectionClickModifiers } from '../../hooks/useRowSelection'
import { SessionRow } from './SessionRow'

interface SelectionProps {
  selectedIds: Set<string>
  onToggleRow: (id: string, modifiers: SelectionClickModifiers) => void
  onSelectAll: () => void
  onClearSelection: () => void
}

interface SessionTableProps {
  rows: SessionSummary[]
  loading: boolean
  emptyState: ReactNode
  selection?: SelectionProps
}

const COLUMNS = [
  { label: 'Status', align: 'left' as const },
  { label: 'Workflow', align: 'left' as const },
  { label: 'Phase', align: 'left' as const },
  { label: 'Model', align: 'left' as const },
  { label: 'Tokens', align: 'right' as const },
  { label: 'Cost', align: 'right' as const },
  { label: 'Duration', align: 'right' as const },
  { label: 'Started', align: 'left' as const },
  { label: '', align: 'right' as const },
]

interface HeaderState {
  allChecked: boolean
  someChecked: boolean
}

function deriveHeaderState(rowCount: number, selection: SelectionProps | undefined): HeaderState {
  if (!selection) return { allChecked: false, someChecked: false }
  const count = selection.selectedIds.size
  return { allChecked: count === rowCount, someChecked: count > 0 && count < rowCount }
}

interface SelectAllCellProps {
  state: HeaderState
  onToggle: () => void
}

function SelectAllCell({ state, onToggle }: SelectAllCellProps) {
  return (
    <th scope="col" className="w-10 px-3 py-2 text-left">
      <SelectionCheckbox
        checked={state.allChecked}
        indeterminate={state.someChecked}
        ariaLabel={state.allChecked ? 'Deselect all sessions' : 'Select all sessions'}
        onChange={onToggle}
      />
    </th>
  )
}

function makeHeaderToggle(
  selection: SelectionProps,
  state: HeaderState,
): () => void {
  return () => {
    if (state.allChecked || state.someChecked) selection.onClearSelection()
    else selection.onSelectAll()
  }
}

function ColumnHeader({ label, align }: { label: string; align: 'left' | 'right' }) {
  return (
    <th
      scope="col"
      className={`px-3 py-2 ${align === 'right' ? 'text-right' : 'text-left'}`}
    >
      {label}
    </th>
  )
}

interface SessionTableHeadProps {
  selection?: SelectionProps
  headerState: HeaderState
}

function SessionTableHead({ selection, headerState }: SessionTableHeadProps) {
  return (
    <thead className="bg-[var(--color-surface-elevated)] text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
      <tr>
        {selection && (
          <SelectAllCell
            state={headerState}
            onToggle={makeHeaderToggle(selection, headerState)}
          />
        )}
        {COLUMNS.map((col) => (
          <ColumnHeader key={col.label || 'actions'} label={col.label} align={col.align} />
        ))}
      </tr>
    </thead>
  )
}

interface SessionTableBodyProps {
  rows: SessionSummary[]
  selection?: SelectionProps
}

function SessionTableBody({ rows, selection }: SessionTableBodyProps) {
  return (
    <tbody>
      {rows.map((session) => (
        <SessionRow
          key={session.id}
          session={session}
          isSelected={selection?.selectedIds.has(session.id) ?? false}
          onToggleSelection={
            selection ? (mods) => selection.onToggleRow(session.id, mods) : undefined
          }
        />
      ))}
    </tbody>
  )
}

export function SessionTable({ rows, loading, emptyState, selection }: SessionTableProps) {
  if (loading) return <PageLoader />
  if (rows.length === 0) return <>{emptyState}</>

  const headerState = deriveHeaderState(rows.length, selection)

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
      <table className="min-w-full text-sm">
        <SessionTableHead selection={selection} headerState={headerState} />
        <SessionTableBody rows={rows} selection={selection} />
      </table>
    </div>
  )
}
