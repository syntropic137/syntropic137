import { request, seg } from '../client'
import type { CostSummary, ExecutionCost, SessionCost } from '../types'
import { cached } from '../keys'

export function listSessionCosts(params: { execution_id?: string; limit?: number } = {}, signal?: AbortSignal): Promise<SessionCost[]> {
  return cached('listSessionCosts', [params], (s) => request('/costs/sessions', { query: { ...params }, signal: s }), { signal, staleAfter: 'list' })
}

export function getSessionCost(sessionId: string, options: { include_breakdown?: boolean } = {}, signal?: AbortSignal): Promise<SessionCost> {
  return cached('getSessionCost', [sessionId, options], (s) => request(`/costs/sessions/${seg(sessionId)}`, { query: { ...options }, signal: s }), { signal })
}

export function listExecutionCosts(params: { limit?: number } = {}, signal?: AbortSignal): Promise<ExecutionCost[]> {
  return cached('listExecutionCosts', [params], (s) => request('/costs/executions', { query: { ...params }, signal: s }), { signal, staleAfter: 'list' })
}

export function getExecutionCost(
  executionId: string,
  options: { include_breakdown?: boolean; include_session_ids?: boolean } = {},
  signal?: AbortSignal,
): Promise<ExecutionCost> {
  return cached('getExecutionCost', [executionId, options], (s) =>
    request(`/costs/executions/${seg(executionId)}`, { query: { ...options }, signal: s }), { signal })
}

export function getCostSummary(signal?: AbortSignal): Promise<CostSummary> {
  return cached('getCostSummary', [], (s) => request('/costs/summary', { signal: s }), { signal, staleAfter: 'metrics' })
}
