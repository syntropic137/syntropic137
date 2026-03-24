import { useEffect, useState } from 'react'

import { getArtifact } from '../api/client'
import type { ArtifactResponse } from '../types'

export interface UseArtifactDataResult {
  artifact: ArtifactResponse | null
  loading: boolean
  error: string | null
}

/**
 * Fetch artifact detail (with content) for a given artifact ID.
 */
export function useArtifactData(artifactId: string | undefined): UseArtifactDataResult {
  const [artifact, setArtifact] = useState<ArtifactResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!artifactId) return

    let cancelled = false
    getArtifact(artifactId, true)
      .then((data) => { if (!cancelled) setArtifact(data) })
      .catch((err) => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [artifactId])

  return { artifact, loading, error }
}
