import { useCallback, useEffect, useState } from 'react'
import { getArtifact } from '../api/artifacts'
import { getExecution } from '../api/executions'
import { useExecutionStream } from './useExecutionStream'
import { useLiveTimer } from './useLiveTimer'
import type { ArtifactResponse, ExecutionDetailResponse } from '../types'
import { SSE_EVENTS } from '../types'

export interface UseExecutionDataResult {
  execution: ExecutionDetailResponse | null
  artifactDetails: Record<string, ArtifactResponse>
  loading: boolean
  error: string | null
  isConnected: boolean
  now: number
  refreshExecution: () => void
}

export function useExecutionData(executionId: string | undefined): UseExecutionDataResult {
  const [execution, setExecution] = useState<ExecutionDetailResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [artifactDetails, setArtifactDetails] = useState<Record<string, ArtifactResponse>>({})

  const isRunning = execution?.status === 'running'
  const now = useLiveTimer(isRunning)

  const refreshExecution = useCallback(() => {
    if (!executionId) return
    getExecution(executionId)
      .then((exec) => setExecution(exec))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [executionId])

  // Initial fetch
  useEffect(() => {
    refreshExecution()
  }, [refreshExecution])

  // SSE subscription for live updates
  const { isConnected } = useExecutionStream(executionId, {
    onEvent: (event) => {
      if (event.type === 'event' && event.event_type) {
        const refreshEvents = [
          'PhaseStarted',
          'PhaseCompleted',
          'WorkflowCompleted',
          'WorkflowFailed',
          'OperationRecorded',
          SSE_EVENTS.WORKSPACE_CREATED,
          SSE_EVENTS.WORKSPACE_DESTROYED,
          SSE_EVENTS.WORKSPACE_ERROR,
        ]
        if (refreshEvents.includes(event.event_type)) {
          refreshExecution()
        }
      }
    },
  })

  // Fetch artifact details when artifact IDs are available
  useEffect(() => {
    if (!execution?.artifact_ids.length) return
    Promise.allSettled(execution.artifact_ids.map((id) => getArtifact(id))).then((results) => {
      const map: Record<string, ArtifactResponse> = {}
      results.forEach((result) => {
        if (result.status === 'fulfilled') {
          map[result.value.id] = result.value
        }
      })
      setArtifactDetails(map)
    })
  }, [execution?.artifact_ids.join(',')]) // eslint-disable-line react-hooks/exhaustive-deps

  return { execution, artifactDetails, loading, error, isConnected, now, refreshExecution }
}
