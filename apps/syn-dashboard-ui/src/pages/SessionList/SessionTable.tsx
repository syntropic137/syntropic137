/**
 * Presentational table that renders a list of session rows.
 *
 * Pure component: takes already-fetched data plus loading/empty slots and
 * renders the table chrome. No data fetching, no business logic.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import type { ReactNode } from 'react'
import { ArrowDown, ArrowUp } from 'lucide-react'
import type { SessionSummary } from '../../types'
import { PageLoader, SelectionCheckbox } from '../../components'
import type { SelectionClickModifiers } from '../../hooks/useRowSelection'
import type { SortKey, SortState } from '../../hooks/useSortUrlState'
import { SessionRow } from './SessionRow'

interface SelectionProps {
  selectedIds: Set<string>
  onToggleRow: (id: string, modifiers: SelectionClickModifiers) => void
  onSelectAll: () => void
  onClearSelection: () => void
}

interface SortProps {
  state: SortState
  onToggle: (key: SortKey) => void
}

interface SessionTableProps {
  rows: SessionSummary[]
  loading: boolean
  emptyState: ReactNode
  selection?: SelectionProps
  sort?: SortProps
}

interface ColumnDef {
  label: string
  align: 'left' | 'right'
  sortKey?: SortKey
}

const COLUMNS: ColumnDef[] = [
  { label: 'Status', align: 'left', sortKey: 'status' },
  { label: 'Workflow', align: 'left', sortKey: 'workflow' },
  { label: 'Phase', align: 'left', sortKey: 'phase' },
  { label: 'Model', align: 'left', sortKey: 'model' },
  { label: 'Tokens', align: 'right', sortKey: 'tokens' },
  { label: 'Cost', align: 'right', sortKey: 'cost' },
  { label: 'Duration', align: 'right', sortKey: 'duration' },
  { label: 'Started', align: 'left', sortKey: 'started' },
  { label: '', align: 'right' },
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

function SortIndicator({ active, dir }: { active: boolean; dir: SortState['dir'] }) {
  if (!active) return null
  const Icon = dir === 'asc' ? ArrowUp : ArrowDown
  return <Icon className="h-3 w-3 text-[var(--color-accent)]" aria-hidden />
}

interface ColumnHeaderProps {
  column: ColumnDef
  sort?: SortProps
}

function ColumnHeader({ column, sort }: ColumnHeaderProps) {
  const alignClass = column.align === 'right' ? 'text-right' : 'text-left'
  const sortable = column.sortKey && sort
  if (!sortable) {
    return <th scope="col" className={`px-3 py-2 ${alignClass}`}>{column.label}</th>
  }
  const key = column.sortKey as SortKey
  const isActive = sort.state.key === key
  const ariaSort = isActive ? (sort.state.dir === 'asc' ? 'ascending' : 'descending') : 'none'
  return (
    <th scope="col" aria-sort={ariaSort} className={`px-3 py-2 ${alignClass}`}>
      <button
        type="button"
        onClick={() => sort.onToggle(key)}
        className={`inline-flex items-center gap-1 uppercase tracking-wide transition-colors hover:text-[var(--color-text-primary)] ${column.align === 'right' ? 'flex-row-reverse' : ''} ${isActive ? 'text-[var(--color-text-primary)]' : ''}`}
      >
        {column.label}
        <SortIndicator active={isActive} dir={sort.state.dir} />
      </button>
    </th>
  )
}

interface SessionTableHeadProps {
  selection?: SelectionProps
  headerState: HeaderState
  sort?: SortProps
}

function SessionTableHead({ selection, headerState, sort }: SessionTableHeadProps) {
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
          <ColumnHeader key={col.label || 'actions'} column={col} sort={sort} />
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

export function SessionTable({
  rows,
  loading,
  emptyState,
  selection,
  sort,
}: SessionTableProps) {
  if (loading) return <PageLoader />
  if (rows.length === 0) return <>{emptyState}</>

  const headerState = deriveHeaderState(rows.length, selection)

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
      <table className="min-w-full text-sm">
        <SessionTableHead selection={selection} headerState={headerState} sort={sort} />
        <SessionTableBody rows={rows} selection={selection} />
      </table>
    </div>
  )
}
