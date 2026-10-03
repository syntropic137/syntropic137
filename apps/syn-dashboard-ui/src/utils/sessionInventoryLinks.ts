/** Deep links into an execution's Sessions view, carried in the URL so they can be shared. */
export const INVENTORY_PHASE_PARAM = 'inventory_phase'
export const INVENTORY_ATTEMPT_PARAM = 'inventory_attempt'
export const SESSION_INVENTORY_ANCHOR = 'session-inventory'

/** Filtered to one phase (and optionally one attempt). Phase ids are membership phase ids. */
export function sessionInventoryHref(executionId: string, phaseId?: string | null, attemptId?: string | null): string {
  const query = new URLSearchParams()
  if (phaseId) query.set(INVENTORY_PHASE_PARAM, phaseId)
  if (attemptId) query.set(INVENTORY_ATTEMPT_PARAM, attemptId)
  const search = query.toString()
  return `/executions/${encodeURIComponent(executionId)}${search ? `?${search}` : ''}#${SESSION_INVENTORY_ANCHOR}`
}
