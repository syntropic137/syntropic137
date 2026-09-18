import { useCallback, useEffect, useState } from 'react'
import { getArtifact } from '../api/artifacts'
import { getExecution } from '../api/executions'
import { useExecutionStream } from './useExecutionStream'
import { useLiveTimer } from './useLiveTimer'
import { RUNNING_POLL_INTERVAL_MS, useSerialRefresh } from './useSerialRefresh'
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

  // `signal` aborts when the execution being viewed changes. Every branch below
  // checks it, because all three would otherwise describe the PREVIOUS
  // execution: its data under this one's id, its failure, or a settled state
  // that belongs to a request this view is no longer waiting on.
  const fetchExecution = useCallback(
    (signal: AbortSignal): Promise<void> => {
      if (!executionId) return Promise.resolve()
      return getExecution(executionId, signal)
        .then((exec) => {
          if (signal.aborted) return
          setExecution(exec)
          // A poll that succeeds clears the last one's failure. Without this the
          // first transient 502 in a run latched `error` for the life of the
          // page, and the detail view rendered "Execution not found" on top of
          // execution data that was still refreshing underneath it (#1048).
          setError(null)
        })
        .catch((err) => {
          if (!signal.aborted) setError(err.message)
        })
        .finally(() => {
          if (!signal.aborted) setLoading(false)
        })
    },
    [executionId],
  )

  // SSE only fires on lifecycle transitions; tokens/cost/duration update
  // continuously, so poll while non-terminal (#1048) - but never on top of a
  // request that has not come back yet (#1095).
  const { refetch: refreshExecution } = useSerialRefresh({
    fetch: fetchExecution,
    pollIntervalMs:
      execution && !isTerminalExecution(execution) ? RUNNING_POLL_INTERVAL_MS : null,
  })

  useEffect(() => {
    refreshExecution()
  }, [refreshExecution, fetchExecution])

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
