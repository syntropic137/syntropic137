import type {
  ExecutionHistoryResponse,
  WorkflowListResponse,
  WorkflowResponse,
} from '../types'
import { API_BASE, fetchJSON } from './base'

export async function listWorkflows(params?: {
  workflow_type?: string
  page?: number
  page_size?: number
  order_by?: string
}): Promise<WorkflowListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.workflow_type) searchParams.set('workflow_type', params.workflow_type)
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))
  if (params?.order_by) searchParams.set('order_by', params.order_by)

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/workflows${query ? `?${query}` : ''}`)
}

export async function getWorkflow(workflowId: string): Promise<WorkflowResponse> {
  return fetchJSON(`${API_BASE}/workflows/${workflowId}`)
}

export async function getWorkflowHistory(workflowId: string): Promise<ExecutionHistoryResponse> {
  return fetchJSON(`${API_BASE}/workflows/${workflowId}/history`)
}

export interface ExecuteWorkflowRequest {
  inputs?: Record<string, string>
  task?: string
  provider?: string
  max_budget_usd?: number
}

export interface ExecuteWorkflowResponse {
  execution_id: string
  workflow_id: string
  status: string
  message: string
}

export async function executeWorkflow(
  workflowId: string,
  request: ExecuteWorkflowRequest = {}
): Promise<ExecuteWorkflowResponse> {
  return fetchJSON(`${API_BASE}/workflows/${workflowId}/execute`, {
    method: 'POST',
    body: JSON.stringify(request),
  })
}
