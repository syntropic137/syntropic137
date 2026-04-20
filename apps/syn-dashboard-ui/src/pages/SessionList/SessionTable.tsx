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
import { PageLoader } from '../../components'
import { SessionRow } from './SessionRow'

interface SessionTableProps {
  rows: SessionSummary[]
  loading: boolean
  emptyState: ReactNode
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

export function SessionTable({ rows, loading, emptyState }: SessionTableProps) {
  if (loading) {
    return <PageLoader />
  }

  if (rows.length === 0) {
    return <>{emptyState}</>
  }

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
      <table className="min-w-full text-sm">
        <thead className="bg-[var(--color-surface-elevated)] text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
          <tr>
            {COLUMNS.map((col) => (
              <th
                key={col.label || 'actions'}
                scope="col"
                className={`px-3 py-2 ${col.align === 'right' ? 'text-right' : 'text-left'}`}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((session) => (
            <SessionRow key={session.id} session={session} />
          ))}
        </tbody>
      </table>
    </div>
  )
}
