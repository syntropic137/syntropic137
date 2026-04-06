import type { SessionResponse, SessionSummary } from '../types'
import { API_BASE, fetchJSON } from './base'

export interface SessionListResponse {
  sessions: SessionSummary[]
  total: number
}

export async function listSessions(params?: {
  workflow_id?: string
  status?: string
  limit?: number
}): Promise<SessionListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.workflow_id) searchParams.set('workflow_id', params.workflow_id)
  if (params?.status) searchParams.set('status', params.status)
  if (params?.limit) searchParams.set('limit', String(params.limit))

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/sessions${query ? `?${query}` : ''}`)
}

export async function getSession(sessionId: string): Promise<SessionResponse> {
  return fetchJSON(`${API_BASE}/sessions/${sessionId}`)
}
