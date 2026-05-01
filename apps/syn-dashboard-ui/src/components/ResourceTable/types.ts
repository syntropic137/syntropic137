/**
 * Shared types for the generic ResourceTable / ResourceCardList primitives.
 *
 * Pages (Sessions, Executions) define a typed sort-key union (`SessionSortKey`,
 * `ExecutionSortKey`) and a list of `ColumnDef<Row>` that describe what each
 * column renders and which sort key it maps to.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import type { ReactNode } from 'react'
import type { SortState } from '../../hooks/useSortUrlState'
import type { SelectionClickModifiers } from '../../hooks/useRowSelection'

export interface ColumnDef<Row, K extends string = string> {
  /** Stable id used as the React key. */
  key: string
  /** Header label shown in the table. Empty string for action columns. */
  label: string
  align?: 'left' | 'right'
  /** When set, the header becomes a sort button bound to this key. */
  sortKey?: K
  /** Renders the cell's contents for one row. */
  render: (row: Row) => ReactNode
  /** Optional native title attr (hover tooltip) for one row's cell. */
  cellTitle?: (row: Row) => string | undefined
  /** Optional Tailwind className applied to <td> for column-specific styling. */
  cellClassName?: string
}

export interface SelectionProps {
  selectedIds: Set<string>
  onToggleRow: (id: string, modifiers: SelectionClickModifiers) => void
  onSelectAll: () => void
  onClearSelection: () => void
}

export interface SortProps<K extends string> {
  state: SortState<K>
  onToggle: (key: K) => void
}

export interface ResourceTableProps<Row, K extends string = string> {
  rows: Row[]
  columns: ColumnDef<Row, K>[]
  loading: boolean
  emptyState: ReactNode
  /** Stable identity per row (used for selection + React keys). */
  getRowId: (row: Row) => string
  /** Optional click target — typically navigates to detail. */
  onRowClick?: (row: Row) => void
  /** Optional last-cell content (copy id, kebab menu, etc.). */
  rowActions?: (row: Row) => ReactNode
  selection?: SelectionProps
  sort?: SortProps<K>
}
