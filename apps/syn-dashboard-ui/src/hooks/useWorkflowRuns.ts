import { useEffect, useState } from 'react'
import { getWorkflow, listExecutions } from '../api/workflows'
import type { WorkflowExecutionSummary, WorkflowResponse } from '../types'

export interface UseWorkflowRunsResult {
  workflow: WorkflowResponse | null
  executions: WorkflowExecutionSummary[]
  loading: boolean
  error: string | null
}

export function useWorkflowRuns(workflowId: string | undefined): UseWorkflowRunsResult {
  const [workflow, setWorkflow] = useState<WorkflowResponse | null>(null)
  const [executions, setExecutions] = useState<WorkflowExecutionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!workflowId) return

    let cancelled = false
    Promise.all([getWorkflow(workflowId), listExecutions(workflowId)])
      .then(([wf, execs]) => {
        if (cancelled) return
        setWorkflow(wf)
        setExecutions(execs)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [workflowId])

  return { workflow, executions, loading, error }
}
