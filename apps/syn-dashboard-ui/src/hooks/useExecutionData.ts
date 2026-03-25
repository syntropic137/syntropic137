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

const REFRESH_EVENT_TYPES = new Set([
  'PhaseStarted',
  'PhaseCompleted',
  'WorkflowCompleted',
  'WorkflowFailed',
  'OperationRecorded',
  SSE_EVENTS.WORKSPACE_CREATED,
  SSE_EVENTS.WORKSPACE_DESTROYED,
  SSE_EVENTS.WORKSPACE_ERROR,
])

function isRefreshEvent(event: { type: string; event_type?: string }): boolean {
  return event.type === 'event' && !!event.event_type && REFRESH_EVENT_TYPES.has(event.event_type)
}

function collectFulfilledArtifacts(results: PromiseSettledResult<ArtifactResponse>[]): Record<string, ArtifactResponse> {
  const map: Record<string, ArtifactResponse> = {}
  for (const result of results) {
    if (result.status === 'fulfilled') {
      map[result.value.id] = result.value
    }
  }
  return map
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

  useEffect(() => {
    refreshExecution()
  }, [refreshExecution])

  const { isConnected } = useExecutionStream(executionId, {
    onEvent: (event) => {
      if (isRefreshEvent(event)) refreshExecution()
    },
  })

  useEffect(() => {
    if (!execution?.artifact_ids.length) return
    Promise.allSettled(execution.artifact_ids.map((id) => getArtifact(id))).then((results) => {
      setArtifactDetails(collectFulfilledArtifacts(results))
    })
  }, [execution?.artifact_ids.join(',')]) // eslint-disable-line react-hooks/exhaustive-deps

  return { execution, artifactDetails, loading, error, isConnected, now, refreshExecution }
}
