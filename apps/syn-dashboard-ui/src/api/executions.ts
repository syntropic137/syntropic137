import type {
  ExecutionDetailResponse,
  ExecutionListResponse,
  WorkflowExecutionSummary,
} from '../types'
import { API_BASE, fetchJSON } from './base'

export async function listExecutions(
  workflowId: string,
  params?: { page?: number; page_size?: number }
): Promise<WorkflowExecutionSummary[]> {
  const searchParams = new URLSearchParams()
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))

  const query = searchParams.toString()
  const response = await fetchJSON<{ runs: WorkflowExecutionSummary[] }>(
    `${API_BASE}/workflows/${workflowId}/runs${query ? `?${query}` : ''}`
  )
  return response.runs ?? []
}

export async function getExecution(executionId: string): Promise<ExecutionDetailResponse> {
  return fetchJSON<ExecutionDetailResponse>(`${API_BASE}/executions/${executionId}`)
}

export async function listAllExecutions(params?: {
  status?: string
  page?: number
  page_size?: number
}): Promise<ExecutionListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.status) searchParams.set('status', params.status)
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/executions${query ? `?${query}` : ''}`)
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
