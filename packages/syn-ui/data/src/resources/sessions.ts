import { type ListQuery, bucketTimeWindow, listQueryParams, request, seg } from '../client'
import type { components } from '../generated/api-types'
import type { SessionResponse } from '../types'
import { cached } from '../keys'

/** The `/sessions` envelope, aliased to the generated type (#1176). */
export type SessionListResponse = components['schemas']['SessionListResponse']
export type SessionListItem = components['schemas']['SessionSummaryResponse']

/** Sessions are additionally scoped to one workflow; every other filter is shared. */
export function listSessions(query: ListQuery & { workflow_id?: string }, signal?: AbortSignal): Promise<SessionListResponse> {
  const q = bucketTimeWindow(query)
  return cached('listSessions', [q], (s) => {
    const params = listQueryParams(q)
    if (q.workflow_id) params.set('workflow_id', q.workflow_id)
    return request('/sessions', { query: params, signal: s })
  }, { signal, staleAfter: 'list' })
}

export function getSession(sessionId: string, signal?: AbortSignal): Promise<SessionResponse> {
  return cached('getSession', [sessionId], (s) => request(`/sessions/${seg(sessionId)}`, { signal: s }), { signal })
}
