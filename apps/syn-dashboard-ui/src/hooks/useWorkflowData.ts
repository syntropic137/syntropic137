import { useEffect, useState } from 'react'
import { getWorkflow, getWorkflowHistory, listExecutions } from '../api/workflows'
import { getMetrics } from '../api/observability'
import { listArtifacts } from '../api/artifacts'
import type {
  ArtifactSummary,
  ExecutionHistoryResponse,
  MetricsResponse,
  WorkflowExecutionSummary,
  WorkflowResponse,
} from '../types'

export interface UseWorkflowDataResult {
  workflow: WorkflowResponse | null
  metrics: MetricsResponse | null
  history: ExecutionHistoryResponse | null
  artifacts: ArtifactSummary[]
  executions: WorkflowExecutionSummary[]
  loading: boolean
  error: string | null
}

export function useWorkflowData(workflowId: string | undefined): UseWorkflowDataResult {
  const [workflow, setWorkflow] = useState<WorkflowResponse | null>(null)
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null)
  const [history, setHistory] = useState<ExecutionHistoryResponse | null>(null)
  const [artifacts, setArtifacts] = useState<ArtifactSummary[]>([])
  const [executions, setExecutions] = useState<WorkflowExecutionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!workflowId) return

    let cancelled = false
    Promise.all([
      getWorkflow(workflowId),
      getMetrics(workflowId),
      getWorkflowHistory(workflowId),
      listArtifacts({ workflow_id: workflowId }),
      listExecutions(workflowId),
    ])
      .then(([wf, met, hist, arts, execs]) => {
        if (cancelled) return
        setWorkflow(wf)
        setMetrics(met)
        setHistory(hist)
        setArtifacts(arts)
        setExecutions(execs)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [workflowId])

  return { workflow, metrics, history, artifacts, executions, loading, error }
}
