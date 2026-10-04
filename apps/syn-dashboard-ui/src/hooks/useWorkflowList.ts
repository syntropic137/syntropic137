import { useCallback, useEffect, useState } from 'react'
import { listWorkflows } from '../api/workflows'
import type { WorkflowSummary } from '../types'
import { SEARCH_DEBOUNCE_MS, useDebounced } from './useListQuery'

export interface UseWorkflowListResult {
  workflows: WorkflowSummary[]
  loading: boolean
  searchQuery: string
  setSearchQuery: (query: string) => void
  typeFilter: string
  setTypeFilter: (type: string) => void
  page: number
  setPage: (page: number) => void
  total: number
  totalPages: number
  pageSize: number
}

const PAGE_SIZE = 20

export function useWorkflowList(): UseWorkflowListResult {
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [total, setTotal] = useState(0)

  // Search runs on the server, before paging: filtering the fetched page here
  // could never find a workflow that lives on page 3.
  const search = useDebounced(searchQuery.trim(), SEARCH_DEBOUNCE_MS)

  // A page number only means something within one filtered collection, so a
  // new search or type IS page 1 - derived, as in useListQuery, rather than
  // reset in an effect that would fetch the stale page first.
  const collectionKey = `${typeFilter} ${search}`
  const [pageState, setPageState] = useState({ collectionKey, page: 1 })
  const page = pageState.collectionKey === collectionKey ? pageState.page : 1
  const setPage = useCallback(
    (next: number) => setPageState({ collectionKey, page: Math.max(1, next) }),
    [collectionKey],
  )

  useEffect(() => {
    let cancelled = false
    listWorkflows({
      workflow_type: typeFilter || undefined,
      search: search || undefined,
      page,
      page_size: PAGE_SIZE,
    })
      .then((data) => {
        if (cancelled) return
        setWorkflows(data.workflows)
        setTotal(data.total)
        setLoading(false)
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
  }, [typeFilter, search, page])

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return {
    workflows,
    loading,
    searchQuery,
    setSearchQuery,
    typeFilter,
    setTypeFilter,
    page,
    setPage,
    total,
    totalPages,
    pageSize: PAGE_SIZE,
  }
}
