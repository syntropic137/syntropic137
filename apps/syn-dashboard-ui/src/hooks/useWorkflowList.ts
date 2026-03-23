import { useEffect, useMemo, useState } from 'react'
import { listWorkflows } from '../api/workflows'
import type { WorkflowSummary } from '../types'

export interface UseWorkflowListResult {
  workflows: WorkflowSummary[]
  filteredWorkflows: WorkflowSummary[]
  loading: boolean
  searchQuery: string
  setSearchQuery: (query: string) => void
  typeFilter: string
  setTypeFilter: (type: string) => void
  page: number
  setPage: React.Dispatch<React.SetStateAction<number>>
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
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)

  useEffect(() => {
    let cancelled = false
    listWorkflows({
      workflow_type: typeFilter || undefined,
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
  }, [typeFilter, page])

  const filteredWorkflows = useMemo(
    () =>
      searchQuery
        ? workflows.filter(
            (w) =>
              w.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
              w.id.toLowerCase().includes(searchQuery.toLowerCase()),
          )
        : workflows,
    [workflows, searchQuery],
  )

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return {
    workflows,
    filteredWorkflows,
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
