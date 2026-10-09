import { request, seg } from '../client'
import type { ExecutionHistoryResponse, WorkflowListResponse, WorkflowResponse } from '../types'
import { cached, thenInvalidate } from '../keys'

export interface ListWorkflowsParams {
  workflow_type?: string
  page?: number
  page_size?: number
  order_by?: string
  search?: string
}

export function listWorkflows(params: ListWorkflowsParams = {}, signal?: AbortSignal): Promise<WorkflowListResponse> {
  return cached('listWorkflows', [params], (s) => request('/workflows', { query: { ...params }, signal: s }), { signal, staleAfter: 'list' })
}

export function getWorkflow(workflowId: string, signal?: AbortSignal): Promise<WorkflowResponse> {
  return cached('getWorkflow', [workflowId], (s) => request(`/workflows/${seg(workflowId)}`, { signal: s }), { signal })
}

export function getWorkflowHistory(workflowId: string, signal?: AbortSignal): Promise<ExecutionHistoryResponse> {
  return cached('getWorkflowHistory', [workflowId], (s) => request(`/workflows/${seg(workflowId)}/history`, { signal: s }), { signal, staleAfter: 'list' })
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

export function executeWorkflow(workflowId: string, body: ExecuteWorkflowRequest = {}): Promise<ExecuteWorkflowResponse> {
  return thenInvalidate(request(`/workflows/${seg(workflowId)}/execute`, { method: 'POST', body }), [
    { name: 'listExecutions' },
    { name: 'listWorkflowRuns', id: workflowId },
    { name: 'getWorkflowHistory', id: workflowId },
    { name: 'getExecutionBudget' },
    { name: 'getMetrics' },
  ])
}

export interface UpdatePhasePromptRequest {
  prompt_template: string
  model?: string | null
  provider?: string | null
  timeout_seconds?: number | null
  allowed_tools?: string[] | null
}

export interface UpdatePhaseResponse {
  workflow_id: string
  phase_id: string
  status: string
}

export function updatePhasePrompt(workflowId: string, phaseId: string, body: UpdatePhasePromptRequest): Promise<UpdatePhaseResponse> {
  return thenInvalidate(request(`/workflows/${seg(workflowId)}/phases/${seg(phaseId)}`, { method: 'PUT', body }), [
    { name: 'getWorkflow', id: workflowId },
    { name: 'listWorkflows' },
  ])
}
