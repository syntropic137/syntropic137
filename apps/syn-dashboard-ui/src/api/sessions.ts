import type { SessionResponse, SessionSummary } from '../types'
import { API_BASE, fetchJSON } from './base'

export interface SessionListResponse {
  sessions: SessionSummary[]
  total: number
}

// DEV ONLY: Model cost enrichment for sessions where the projection doesn't have model-tagged data.
// TODO(#599): Remove once new workflow executions populate cost_by_model in the SessionCost projection.
const _DEV_SESSION_MODEL_DATA: Record<string, Record<string, string>> = {
  '8053d0e6-e9a9-45aa-ac4d-beeb2cf2f8c8': { 'claude-sonnet-4-20250514': '0.0184' },
  '63d9a6bf-5788-473a-a84e-e7663d916554': { 'claude-opus-4-20250514': '0.0250', 'claude-haiku-4-5-20251001': '0.0099' },
  '38bcc2ae-b7be-4887-b274-31f2aefdcd43': { 'claude-sonnet-4-20250514': '0.0704' },
}

const _ENABLE_DEV_ENRICHMENT = import.meta.env.DEV

function _enrichSession(data: SessionResponse): SessionResponse {
  if (!_ENABLE_DEV_ENRICHMENT) return data
  if (!data.cost_by_model || Object.keys(data.cost_by_model).length === 0) {
    const dev = _DEV_SESSION_MODEL_DATA[data.id]
    if (dev) {
      data.cost_by_model = dev
    }
  }
  return data
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
  const data = await fetchJSON<SessionResponse>(`${API_BASE}/sessions/${sessionId}`)
  return _enrichSession(data)
}
