/**
 * Sessions table — thin adapter over the generic ResourceTable.
 *
 * Owns only the per-row navigation target and the trailing copy-id action;
 * everything else (sort, selection, header chrome, mobile fallback) is shared
 * with the Executions table via the ResourceTable primitive.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useNavigate } from 'react-router-dom'
import { Copy } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { ResourceTable } from '../../components'
import type {
  ResourceTableProps,
  SelectionProps,
  SortProps,
} from '../../components/ResourceTable/types'
import type { SessionSummary } from '../../types'
import type { SortKey } from '../../hooks/useSortUrlState'
import { SESSION_COLUMNS } from './sessionColumns'

interface SessionTableProps {
  rows: SessionSummary[]
  loading: boolean
  emptyState: ReactNode
  selection?: SelectionProps
  sort?: SortProps<SortKey>
}

function CopyIdButton({ id }: { id: string }) {
  const [copied, setCopied] = useState(false)
  const onClick = async (e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await navigator.clipboard.writeText(id)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch {
      // ignore — clipboard API can fail in older browsers
    }
  }
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Copy id"
      title={copied ? 'Copied!' : 'Copy id'}
      className="inline-flex h-9 w-9 items-center justify-center rounded text-[var(--color-text-muted)] transition-colors hover:bg-[var(--color-surface)] hover:text-[var(--color-text-primary)] md:invisible md:h-auto md:w-auto md:p-1 md:group-hover:visible"
    >
      <Copy className="h-4 w-4 md:h-3.5 md:w-3.5" />
    </button>
  )
}

export function SessionTable({ rows, loading, emptyState, selection, sort }: SessionTableProps) {
  const navigate = useNavigate()
  const props: ResourceTableProps<SessionSummary, SortKey> = {
    rows,
    columns: SESSION_COLUMNS,
    loading,
    emptyState,
    getRowId: (s) => s.id,
    onRowClick: (s) => navigate(`/sessions/${s.id}`),
    rowActions: (s) => <CopyIdButton id={s.id} />,
    selection,
    sort,
  }
  return <ResourceTable {...props} />
}
