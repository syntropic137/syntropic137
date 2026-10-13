import { request, seg } from '../client'
import { type QueryTarget, cached, thenInvalidate } from '../keys'

export interface TriggerSummary {
  trigger_id: string
  name: string
  event: string
  repository: string
  workflow_id: string
  workflow_name?: string
  status: string
  fire_count: number
}

export interface TriggerDetail extends TriggerSummary {
  conditions: Record<string, unknown> | null
  installation_id: string
  input_mapping: Record<string, unknown> | null
  config: Record<string, unknown> | null
  created_by: string
}

export interface TriggerHistoryEntry {
  fired_at: string | null
  execution_id: string | null
  webhook_delivery_id?: string | null
  event_type: string | null
  pr_number: number | null
  status: string | null
  cost_usd?: number | null
  trigger_id?: string
}

export interface TriggerListResponse {
  triggers: TriggerSummary[]
  total: number
}

export function listTriggers(params: { repository?: string; status?: string } = {}, signal?: AbortSignal): Promise<TriggerListResponse> {
  return cached('listTriggers', [params], (s) => request('/triggers', { query: { ...params }, signal: s }), { signal, staleAfter: 'list' })
}

export function getTrigger(triggerId: string, signal?: AbortSignal): Promise<TriggerDetail> {
  return cached('getTrigger', [triggerId], (s) => request(`/triggers/${seg(triggerId)}`, { signal: s }), { signal })
}

export function deleteTrigger(triggerId: string): Promise<{ trigger_id: string; status: string }> {
  return thenInvalidate(request(`/triggers/${seg(triggerId)}`, { method: 'DELETE' }), triggerTargets(triggerId))
}

export function updateTrigger(
  triggerId: string,
  action: 'pause' | 'resume',
  reason?: string,
): Promise<{ trigger_id: string; status: string; action: string }> {
  return thenInvalidate(request(`/triggers/${seg(triggerId)}`, { method: 'PATCH', body: { action, reason } }), triggerTargets(triggerId))
}

export function getTriggerHistory(
  triggerId: string,
  limit = 50,
  signal?: AbortSignal,
): Promise<{ trigger_id: string; entries: TriggerHistoryEntry[] }> {
  return cached('getTriggerHistory', [triggerId, limit], (s) => request(`/triggers/${seg(triggerId)}/history`, { query: { limit }, signal: s }), {
    signal,
    staleAfter: 'list',
  })
}

const triggerTargets = (triggerId: string): QueryTarget[] => [
  { name: 'listTriggers' },
  { name: 'getTrigger', id: triggerId },
  { name: 'getTriggerHistory', id: triggerId },
]
