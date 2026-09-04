import type { components } from '../generated/api-types'
import type { SessionResponse } from '../types'
import { API_BASE, fetchJSON } from './base'
import { listQueryParams, type ListQuery } from './listQuery'

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

/** Sessions are additionally scoped to one workflow; every other filter is shared. */
export async function listSessions(
  query: ListQuery & { workflow_id?: string },
): Promise<SessionListResponse> {
  const params = listQueryParams(query)
  if (query.workflow_id) params.set('workflow_id', query.workflow_id)
  return fetchJSON(`${API_BASE}/sessions?${params}`)
}

export async function getSession(sessionId: string, signal?: AbortSignal): Promise<SessionResponse> {
  return fetchJSON<SessionResponse>(`${API_BASE}/sessions/${sessionId}`, { signal })
}
