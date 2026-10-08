import { request, seg } from '../client'
import type { CostSummary, ExecutionCost, SessionCost } from '../types'

export function listSessionCosts(params: { execution_id?: string; limit?: number } = {}, signal?: AbortSignal): Promise<SessionCost[]> {
  return request('/costs/sessions', { query: { ...params }, signal })
}

export function getSessionCost(sessionId: string, options: { include_breakdown?: boolean } = {}, signal?: AbortSignal): Promise<SessionCost> {
  return request(`/costs/sessions/${seg(sessionId)}`, { query: { ...options }, signal })
}

export function listExecutionCosts(params: { limit?: number } = {}, signal?: AbortSignal): Promise<ExecutionCost[]> {
  return request('/costs/executions', { query: { ...params }, signal })
}

export function getExecutionCost(
  executionId: string,
  options: { include_breakdown?: boolean; include_session_ids?: boolean } = {},
  signal?: AbortSignal,
): Promise<ExecutionCost> {
  return request(`/costs/executions/${seg(executionId)}`, { query: { ...options }, signal })
}

export function getCostSummary(signal?: AbortSignal): Promise<CostSummary> {
  return request('/costs/summary', { signal })
}
