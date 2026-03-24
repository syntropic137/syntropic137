import type { CostSummary, ExecutionCost, SessionCost } from '../types'
import { API_BASE, fetchJSON } from './base'

export async function listSessionCosts(params?: {
  execution_id?: string
  limit?: number
}): Promise<SessionCost[]> {
  const searchParams = new URLSearchParams()
  if (params?.execution_id) searchParams.set('execution_id', params.execution_id)
  if (params?.limit) searchParams.set('limit', String(params.limit))

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/costs/sessions${query ? `?${query}` : ''}`)
}

export async function getSessionCost(
  sessionId: string,
  options?: { include_breakdown?: boolean }
): Promise<SessionCost> {
  const searchParams = new URLSearchParams()
  if (options?.include_breakdown !== undefined) {
    searchParams.set('include_breakdown', String(options.include_breakdown))
  }

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/costs/sessions/${sessionId}${query ? `?${query}` : ''}`)
}

export async function listExecutionCosts(params?: {
  limit?: number
}): Promise<ExecutionCost[]> {
  const searchParams = new URLSearchParams()
  if (params?.limit) searchParams.set('limit', String(params.limit))

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/costs/executions${query ? `?${query}` : ''}`)
}

export async function getExecutionCost(
  executionId: string,
  options?: { include_breakdown?: boolean; include_session_ids?: boolean }
): Promise<ExecutionCost> {
  const searchParams = new URLSearchParams()
  if (options?.include_breakdown !== undefined) {
    searchParams.set('include_breakdown', String(options.include_breakdown))
  }
  if (options?.include_session_ids !== undefined) {
    searchParams.set('include_session_ids', String(options.include_session_ids))
  }

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/costs/executions/${executionId}${query ? `?${query}` : ''}`)
}

export async function getCostSummary(): Promise<CostSummary> {
  return fetchJSON(`${API_BASE}/costs/summary`)
}
