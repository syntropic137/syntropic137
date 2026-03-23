import { useCallback, useEffect, useMemo, useState } from 'react'
import { listTriggers, type TriggerSummary } from '../api/triggers'

export interface UseTriggerListResult {
  triggers: TriggerSummary[]
  setTriggers: React.Dispatch<React.SetStateAction<TriggerSummary[]>>
  filteredTriggers: TriggerSummary[]
  loading: boolean
  error: string | null
  setError: React.Dispatch<React.SetStateAction<string | null>>
  searchQuery: string
  setSearchQuery: (query: string) => void
  statusFilter: string
  setStatusFilter: (status: string) => void
  fetchTriggers: (showLoader?: boolean) => void
}

export function useTriggerList(): UseTriggerListResult {
  const [triggers, setTriggers] = useState<TriggerSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  const fetchTriggers = useCallback(
    (showLoader = true) => {
      if (showLoader) setLoading(true)
      setError(null)
      listTriggers({ status: statusFilter || undefined })
        .then((data) => {
          setTriggers(data.triggers)
          setLoading(false)
        })
        .catch((err) => {
          console.error(err)
          setError(err instanceof Error ? err.message : 'Failed to load triggers')
          setLoading(false)
        })
    },
    [statusFilter],
  )

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetchTriggers is an async data loader, setState happens in the .then callback, not synchronously in the effect body
    fetchTriggers()
  }, [fetchTriggers])

  const filteredTriggers = useMemo(
    () =>
      searchQuery
        ? triggers.filter(
            (t) =>
              t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
              t.repository.toLowerCase().includes(searchQuery.toLowerCase()) ||
              t.event.toLowerCase().includes(searchQuery.toLowerCase()),
          )
        : triggers,
    [triggers, searchQuery],
  )

  return {
    triggers,
    setTriggers,
    filteredTriggers,
    loading,
    error,
    setError,
    searchQuery,
    setSearchQuery,
    statusFilter,
    setStatusFilter,
    fetchTriggers,
  }
}
