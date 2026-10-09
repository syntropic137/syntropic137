import { type ListQuery, bucketTimeWindow, listQueryParams, request, seg } from '../client'
import type {
  ExecutionBudgetInfo,
  ExecutionDetailResponse,
  ExecutionListResponse,
  WorkflowExecutionSummary,
} from '../types'
import { cached, thenInvalidate } from '../keys'

/**
 * Every run of one workflow. `/workflows/{id}/runs` declares no paging and
 * returns the full list (the server refuses undeclared params, #1313).
 */
export function listWorkflowRuns(workflowId: string, signal?: AbortSignal): Promise<WorkflowExecutionSummary[]> {
  return cached('listWorkflowRuns', [workflowId], async (s) => {
    const response = await request<{ runs?: WorkflowExecutionSummary[] }>(`/workflows/${seg(workflowId)}/runs`, { signal: s })
    return response.runs ?? []
  }, { signal, staleAfter: 'list' })
}

export function getExecution(executionId: string, signal?: AbortSignal): Promise<ExecutionDetailResponse> {
  return cached('getExecution', [executionId], (s) => request(`/executions/${seg(executionId)}`, { signal: s }), { signal })
}

/** One page of executions across every workflow (shared list query, #1159). */
export function listExecutions(query: ListQuery, signal?: AbortSignal): Promise<ExecutionListResponse> {
  const q = bucketTimeWindow(query)
  return cached('listExecutions', [q], (s) => request('/executions', { query: listQueryParams(q), signal: s }), { signal, staleAfter: 'list' })
}

/** The execution budget's occupancy, which the list reports beside every page (PC-124). */
export function getExecutionBudget(signal?: AbortSignal): Promise<ExecutionBudgetInfo | null> {
  return cached('getExecutionBudget', [], async (s) => {
    const response = await request<ExecutionListResponse>('/executions', { query: { page_size: 1 }, signal: s })
    return response.budget ?? null
  }, { signal, staleAfter: 'metrics' })
}

export interface CancelExecutionResponse {
  success: boolean
  execution_id: string
  state: string
  message: string | null
}

export function cancelExecution(executionId: string, reason = 'Cancelled from UI'): Promise<CancelExecutionResponse> {
  return thenInvalidate(request(`/executions/${seg(executionId)}/cancel`, { method: 'POST', body: { reason } }), [
    { name: 'getExecution', id: executionId },
    { name: 'listExecutions' },
    { name: 'listWorkflowRuns' },
    { name: 'getExecutionBudget' },
  ])
}
