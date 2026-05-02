import type { SessionResponse, SessionSummary } from '../types'
import { API_BASE, fetchJSON } from './base'

export interface SessionListResponse {
  sessions: SessionSummary[]
  total: number
}

export async function listSessions(params?: {
  workflow_id?: string
  status?: string
  /** Comma-joined OR'd status filter; takes precedence over `status`. */
  statuses?: string[]
  /** Inclusive ISO 8601 lower bound on started_at. */
  started_after?: string
  /** Inclusive ISO 8601 upper bound on started_at. */
  started_before?: string
  limit?: number
}): Promise<SessionListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.workflow_id) searchParams.set('workflow_id', params.workflow_id)
  if (params?.status) searchParams.set('status', params.status)
  if (params?.statuses && params.statuses.length > 0) {
    searchParams.set('statuses', params.statuses.join(','))
  }
  if (params?.started_after) searchParams.set('started_after', params.started_after)
  if (params?.started_before) searchParams.set('started_before', params.started_before)
  if (params?.limit) searchParams.set('limit', String(params.limit))

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/sessions${query ? `?${query}` : ''}`)
}

export async function getSession(sessionId: string, signal?: AbortSignal): Promise<SessionResponse> {
  return fetchJSON<SessionResponse>(`${API_BASE}/sessions/${sessionId}`, { signal })
}
