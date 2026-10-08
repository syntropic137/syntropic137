import { type ListQuery, listQueryParams, request, seg } from '../client'
import type {
  ExecutionBudgetInfo,
  ExecutionDetailResponse,
  ExecutionListResponse,
  WorkflowExecutionSummary,
} from '../types'

/**
 * Every run of one workflow. `/workflows/{id}/runs` declares no paging and
 * returns the full list (the server refuses undeclared params, #1313).
 */
export async function listWorkflowRuns(workflowId: string, signal?: AbortSignal): Promise<WorkflowExecutionSummary[]> {
  const response = await request<{ runs?: WorkflowExecutionSummary[] }>(`/workflows/${seg(workflowId)}/runs`, { signal })
  return response.runs ?? []
}

export function getExecution(executionId: string, signal?: AbortSignal): Promise<ExecutionDetailResponse> {
  return request(`/executions/${seg(executionId)}`, { signal })
}

/** One page of executions across every workflow (shared list query, #1159). */
export function listExecutions(query: ListQuery, signal?: AbortSignal): Promise<ExecutionListResponse> {
  return request('/executions', { query: listQueryParams(query), signal })
}

/** The execution budget's occupancy, which the list reports beside every page (PC-124). */
export async function getExecutionBudget(signal?: AbortSignal): Promise<ExecutionBudgetInfo | null> {
  const response = await request<ExecutionListResponse>('/executions', { query: { page_size: 1 }, signal })
  return response.budget ?? null
}

export interface CancelExecutionResponse {
  success: boolean
  execution_id: string
  state: string
  message: string | null
}

export function cancelExecution(executionId: string, reason = 'Cancelled from UI'): Promise<CancelExecutionResponse> {
  return request(`/executions/${seg(executionId)}/cancel`, { method: 'POST', body: { reason } })
}
