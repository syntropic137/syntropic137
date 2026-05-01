/**
 * Mobile card-list rendering of sessions.
 *
 * Thin adapter over ResourceCardList: contributes a renderCard fn that maps
 * SessionSummary → SessionCard inner content. The wrapper, selection, and
 * tap-to-detail behaviour are shared with Executions via ResourceCardList.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { ResourceCardList } from '../../components'
import type { SelectionProps } from '../../components/ResourceTable/types'
import type { SessionSummary } from '../../types'
import { SessionCard } from './SessionCard'

interface SessionCardListProps {
  rows: SessionSummary[]
  loading: boolean
  emptyState: ReactNode
  selection?: SelectionProps
}

export function SessionCardList({ rows, loading, emptyState, selection }: SessionCardListProps) {
  const navigate = useNavigate()
  return (
    <ResourceCardList<SessionSummary>
      rows={rows}
      loading={loading}
      emptyState={emptyState}
      selection={selection}
      getRowId={(s) => s.id}
      onRowClick={(s) => navigate(`/sessions/${s.id}`)}
      renderCard={(s) => <SessionCard session={s} />}
    />
  )
}
