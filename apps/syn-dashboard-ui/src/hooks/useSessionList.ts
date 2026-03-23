import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listSessions } from '../api/sessions'
import type { SessionSummary } from '../types'

export interface UseSessionListResult {
  sessions: SessionSummary[]
  filteredSessions: SessionSummary[]
  loading: boolean
  searchQuery: string
  setSearchQuery: (query: string) => void
  statusFilter: string
  setStatusFilter: (status: string) => void
}

export function useSessionList(): UseSessionListResult {
  const [searchParams] = useSearchParams()
  const workflowIdFilter = searchParams.get('workflow_id') ?? ''

  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  useEffect(() => {
    let cancelled = false
    listSessions({
      workflow_id: workflowIdFilter || undefined,
      status: statusFilter || undefined,
      limit: 100,
    })
      .then((data) => {
        if (!cancelled) {
          setSessions(data)
          setLoading(false)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          console.error(err)
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [workflowIdFilter, statusFilter])

  const filteredSessions = useMemo(
    () =>
      searchQuery
        ? sessions.filter(
            (s) =>
              s.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
              s.workflow_id?.toLowerCase().includes(searchQuery.toLowerCase()),
          )
        : sessions,
    [sessions, searchQuery],
  )

  return {
    sessions,
    filteredSessions,
    loading,
    searchQuery,
    setSearchQuery,
    statusFilter,
    setStatusFilter,
  }
}
