import type { components } from '../generated/api-types'
import type { SessionResponse } from '../types'
import { API_BASE, fetchJSON } from './base'

/**
 * The `/sessions` envelope, aliased to the generated type rather than restated.
 *
 * Restated by hand it declared only `sessions` and `total`, so `page`,
 * `page_size` and `status_counts` were not merely unread - they were
 * unreachable, and reading one would have been `undefined` rather than a type
 * error. Nothing regenerates a hand-written interface and no drift gate sees
 * it: `check:api-drift` compares the SPEC to the GENERATED types and never
 * looks at a type someone wrote next to them. That is #1176 one layer out.
 */
export type SessionListResponse = components['schemas']['SessionListResponse']

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
