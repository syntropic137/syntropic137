import type {
  ExecutionDetailResponse,
  ExecutionListResponse,
  WorkflowExecutionSummary,
} from '../types'
import { API_BASE, fetchJSON } from './base'
import { listQueryParams, type ListQuery } from './listQuery'

/**
 * Every run of one workflow.
 *
 * This used to accept `page`/`page_size` and put them on the query string, but
 * `/workflows/{id}/runs` declares neither and returns the full list, so paging
 * here selected nothing - no caller ever passed them. Removed rather than
 * honoured: the server now refuses a parameter it does not declare (#1313), so
 * the dead argument was a 422 waiting for its first user. Paging this endpoint
 * is a server-side change first.
 */
export async function listExecutions(
  workflowId: string
): Promise<WorkflowExecutionSummary[]> {
  const response = await fetchJSON<{ runs: WorkflowExecutionSummary[] }>(
    `${API_BASE}/workflows/${workflowId}/runs`
  )
  return response.runs ?? []
}

export async function getExecution(executionId: string): Promise<ExecutionDetailResponse> {
  return fetchJSON<ExecutionDetailResponse>(`${API_BASE}/executions/${executionId}`)
}

export async function listAllExecutions(query: ListQuery): Promise<ExecutionListResponse> {
  return fetchJSON(`${API_BASE}/executions?${listQueryParams(query)}`)
}

export async function pauseExecution(
  executionId: string,
  reason?: string
): Promise<{ success: boolean; execution_id: string; state: string; message: string | null }> {
  return fetchJSON(`${API_BASE}/executions/${executionId}/pause`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

export async function resumeExecution(
  executionId: string
): Promise<{ success: boolean; execution_id: string; state: string; message: string | null }> {
  return fetchJSON(`${API_BASE}/executions/${executionId}/resume`, {
    method: 'POST',
  })
}

export async function cancelExecution(
  executionId: string,
  reason?: string
): Promise<{ success: boolean; execution_id: string; state: string; message: string | null }> {
  return fetchJSON(`${API_BASE}/executions/${executionId}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ reason: reason ?? 'Cancelled from UI' }),
  })
}
