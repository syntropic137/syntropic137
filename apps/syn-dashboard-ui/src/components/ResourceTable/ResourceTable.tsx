/**
 * Generic, sortable, multi-selectable table for the dashboard.
 *
 * Sessions and Executions both render a dense table with the same chrome:
 * sticky-headered, sortable columns, optional select-all checkbox, hover row
 * highlight, click-to-detail, and a final per-row actions slot. This component
 * owns that chrome; pages provide a typed ColumnDef list.
 *
 * Mobile (below `md:`) is a separate concern: see ResourceCardList.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { ArrowDown, ArrowUp } from 'lucide-react'
import type { ReactNode } from 'react'
import { clsx } from 'clsx'
import { PageLoader, SelectionCheckbox } from '..'
import type { SortState } from '../../hooks/useSortUrlState'
import type {
  ColumnDef,
  ResourceTableProps,
  SelectionProps,
  SortProps,
} from './types'

interface HeaderState {
  allChecked: boolean
  someChecked: boolean
}

function deriveHeaderState(rowCount: number, selection: SelectionProps | undefined): HeaderState {
  if (!selection) return { allChecked: false, someChecked: false }
  const count = selection.selectedIds.size
  return { allChecked: count > 0 && count === rowCount, someChecked: count > 0 && count < rowCount }
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
        ariaLabel={state.allChecked ? 'Deselect all' : 'Select all'}
        onChange={onToggle}
      />
    </th>
  )
}

function makeHeaderToggle(selection: SelectionProps, state: HeaderState): () => void {
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

interface ColumnHeaderProps<Row, K extends string> {
  column: ColumnDef<Row, K>
  sort?: SortProps<K>
}

function ColumnHeader<Row, K extends string>({ column, sort }: ColumnHeaderProps<Row, K>) {
  const align = column.align ?? 'left'
  const alignClass = align === 'right' ? 'text-right' : 'text-left'
  const sortable = column.sortKey !== undefined && sort !== undefined
  if (!sortable || !column.sortKey || !sort) {
    return <th scope="col" className={clsx('px-3 py-2', alignClass)}>{column.label}</th>
  }
  const key = column.sortKey
  const isActive = sort.state.key === key
  const ariaSort = isActive ? (sort.state.dir === 'asc' ? 'ascending' : 'descending') : 'none'
  return (
    <th scope="col" aria-sort={ariaSort} className={clsx('px-3 py-2', alignClass)}>
      <button
        type="button"
        onClick={() => sort.onToggle(key)}
        className={clsx(
          'inline-flex items-center gap-1 uppercase tracking-wide transition-colors hover:text-[var(--color-text-primary)]',
          align === 'right' && 'flex-row-reverse',
          isActive && 'text-[var(--color-text-primary)]',
        )}
      >
        {column.label}
        <SortIndicator active={isActive} dir={sort.state.dir} />
      </button>
    </th>
  )
}

interface TableHeadProps<Row, K extends string> {
  columns: ColumnDef<Row, K>[]
  selection?: SelectionProps
  headerState: HeaderState
  sort?: SortProps<K>
  hasActions: boolean
}

function TableHead<Row, K extends string>({
  columns,
  selection,
  headerState,
  sort,
  hasActions,
}: TableHeadProps<Row, K>) {
  return (
    <thead className="bg-[var(--color-surface-elevated)] text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
      <tr>
        {selection && (
          <SelectAllCell state={headerState} onToggle={makeHeaderToggle(selection, headerState)} />
        )}
        {columns.map((col) => (
          <ColumnHeader key={col.key} column={col} sort={sort} />
        ))}
        {hasActions && <th scope="col" className="px-3 py-2 text-right" />}
      </tr>
    </thead>
  )
}

interface TableRowProps<Row, K extends string> {
  row: Row
  rowId: string
  columns: ColumnDef<Row, K>[]
  isSelected: boolean
  onToggleSelection?: (modifiers: { shift: boolean; meta: boolean }) => void
  onClick?: () => void
  actions?: ReactNode
}

function rowKeyHandler(onClick: (() => void) | undefined): (e: React.KeyboardEvent) => void {
  return (e) => {
    if (!onClick) return
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onClick()
    }
  }
}

function TableRow<Row, K extends string>({
  row,
  rowId,
  columns,
  isSelected,
  onToggleSelection,
  onClick,
  actions,
}: TableRowProps<Row, K>) {
  return (
    <tr
      onClick={onClick}
      onKeyDown={rowKeyHandler(onClick)}
      tabIndex={onClick ? 0 : -1}
      role={onClick ? 'button' : undefined}
      title={rowId}
      className={clsx(
        'group border-b border-[var(--color-border)] transition-colors hover:bg-[var(--color-surface-elevated)] focus:bg-[var(--color-surface-elevated)] focus:outline-none',
        onClick && 'cursor-pointer',
        isSelected && 'bg-[var(--color-accent)]/10',
      )}
    >
      {onToggleSelection && (
        <td className="w-10 px-3 py-2">
          <SelectionCheckbox
            checked={isSelected}
            ariaLabel={isSelected ? `Deselect ${rowId}` : `Select ${rowId}`}
            onChange={(e) =>
              onToggleSelection({ shift: e.shiftKey, meta: e.metaKey || e.ctrlKey })
            }
          />
        </td>
      )}
      {columns.map((col) => {
        const align = col.align ?? 'left'
        return (
          <td
            key={col.key}
            className={clsx(
              'px-3 py-2',
              align === 'right' ? 'text-right' : 'text-left',
              col.cellClassName,
            )}
            title={col.cellTitle?.(row)}
          >
            {col.render(row)}
          </td>
        )
      })}
      {actions !== undefined && <td className="px-3 py-2 text-right">{actions}</td>}
    </tr>
  )
}

export function ResourceTable<Row, K extends string = string>({
  rows,
  columns,
  loading,
  emptyState,
  getRowId,
  onRowClick,
  rowActions,
  selection,
  sort,
}: ResourceTableProps<Row, K>) {
  if (loading) return <PageLoader />
  if (rows.length === 0) return <>{emptyState}</>

  const headerState = deriveHeaderState(rows.length, selection)
  const hasActions = rowActions !== undefined

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
      <table className="w-full min-w-[720px] text-sm">
        <TableHead
          columns={columns}
          selection={selection}
          headerState={headerState}
          sort={sort}
          hasActions={hasActions}
        />
        <tbody>
          {rows.map((row) => {
            const id = getRowId(row)
            return (
              <TableRow
                key={id}
                row={row}
                rowId={id}
                columns={columns}
                isSelected={selection?.selectedIds.has(id) ?? false}
                onToggleSelection={
                  selection ? (mods) => selection.onToggleRow(id, mods) : undefined
                }
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                actions={rowActions ? rowActions(row) : undefined}
              />
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
