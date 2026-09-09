import { useCallback, useEffect, useState } from 'react'
import { getArtifact } from '../api/artifacts'
import { getExecution } from '../api/executions'
import { useLiveRecord } from './useLiveRecord'
import { useLiveTimer } from './useLiveTimer'
import type { ArtifactResponse, ExecutionDetailResponse } from '../types'
import { SSE_EVENTS } from '../types'
import { isTerminalExecutionStatus } from '../utils/terminalStatus'

export interface UseExecutionDataResult {
  execution: ExecutionDetailResponse | null
  artifactDetails: Record<string, ArtifactResponse>
  loading: boolean
  error: string | null
  isConnected: boolean
  now: number
  refreshExecution: () => void
}

function isTerminalExecution(e: ExecutionDetailResponse): boolean {
  return isTerminalExecutionStatus(e.status)
}

// Everything that moves this view. `OperationRecorded` is what makes the
// tokens and cost tick, and `ArtifactCreated` is what makes an artifact appear
// mid-run; both used to arrive only via the 3s poll, the first because it was
// never routable at all and the second because it was simply missing here
// (#1095).
const REFRESH_EVENT_TYPES: ReadonlySet<string> = new Set([
  'PhaseStarted',
  'PhaseCompleted',
  'WorkflowCompleted',
  'WorkflowFailed',
  'OperationRecorded',
  'ArtifactCreated',
  SSE_EVENTS.WORKSPACE_CREATED,
  SSE_EVENTS.WORKSPACE_DESTROYED,
  SSE_EVENTS.WORKSPACE_ERROR,
])

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
      .then((exec) => {
        setExecution(exec)
        // A poll that succeeds clears the last one's failure. Without this the
        // first transient 502 in a run latched `error` for the life of the
        // page, and the detail view rendered "Execution not found" on top of
        // execution data that was still refreshing underneath it (#1048).
        setError(null)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [executionId])

  useEffect(() => {
    refreshExecution()
  }, [refreshExecution])

  // Every frame on this channel belongs to this execution, so no narrowing.
  const { connected: isConnected } = useLiveRecord({
    executionId,
    record: execution,
    isTerminal: isTerminalExecution,
    refetch: refreshExecution,
    liveEvents: REFRESH_EVENT_TYPES,
  })

  useEffect(() => {
    if (!execution?.artifact_ids.length) return
    Promise.allSettled(execution.artifact_ids.map((id) => getArtifact(id))).then((results) => {
      setArtifactDetails(collectFulfilledArtifacts(results))
    })
  }, [execution?.artifact_ids.join(',')]) // eslint-disable-line react-hooks/exhaustive-deps

  return { execution, artifactDetails, loading, error, isConnected, now, refreshExecution }
}
