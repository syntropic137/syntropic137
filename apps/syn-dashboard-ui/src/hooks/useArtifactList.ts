import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listArtifacts } from '../api/artifacts'
import type { ArtifactSummary } from '../types'

export interface UseArtifactListResult {
  artifacts: ArtifactSummary[]
  filteredArtifacts: ArtifactSummary[]
  loading: boolean
  searchQuery: string
  setSearchQuery: (query: string) => void
  typeFilter: string
  setTypeFilter: (type: string) => void
}

export function useArtifactList(): UseArtifactListResult {
  const [searchParams] = useSearchParams()
  const workflowIdFilter = searchParams.get('workflow_id') ?? ''
  const phaseIdFilter = searchParams.get('phase_id') ?? ''

  const [artifacts, setArtifacts] = useState<ArtifactSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<string>('')

  useEffect(() => {
    let cancelled = false
    listArtifacts({
      workflow_id: workflowIdFilter || undefined,
      phase_id: phaseIdFilter || undefined,
      artifact_type: typeFilter || undefined,
      limit: 100,
    })
      .then((data) => {
        if (!cancelled) {
          setArtifacts(data)
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
  }, [workflowIdFilter, phaseIdFilter, typeFilter])

  const filteredArtifacts = useMemo(
    () =>
      searchQuery
        ? artifacts.filter(
            (a) =>
              a.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
              a.title?.toLowerCase().includes(searchQuery.toLowerCase()),
          )
        : artifacts,
    [artifacts, searchQuery],
  )

  return {
    artifacts,
    filteredArtifacts,
    loading,
    searchQuery,
    setSearchQuery,
    typeFilter,
    setTypeFilter,
  }
}
