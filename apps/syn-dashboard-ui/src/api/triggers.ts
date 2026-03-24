import { API_BASE, fetchJSON } from './base'

export interface TriggerSummary {
  trigger_id: string
  name: string
  event: string
  repository: string
  workflow_id: string
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

export async function listTriggers(params?: {
  repository?: string
  status?: string
}): Promise<{ triggers: TriggerSummary[]; total: number }> {
  const searchParams = new URLSearchParams()
  if (params?.repository) searchParams.set('repository', params.repository)
  if (params?.status) searchParams.set('status', params.status)

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/triggers${query ? `?${query}` : ''}`)
}

export async function getTrigger(triggerId: string): Promise<TriggerDetail> {
  return fetchJSON(`${API_BASE}/triggers/${triggerId}`)
}

export async function deleteTrigger(triggerId: string): Promise<{ trigger_id: string; status: string }> {
  return fetchJSON(`${API_BASE}/triggers/${triggerId}`, { method: 'DELETE' })
}

export async function updateTrigger(
  triggerId: string,
  action: 'pause' | 'resume',
  reason?: string
): Promise<{ trigger_id: string; status: string; action: string }> {
  return fetchJSON(`${API_BASE}/triggers/${triggerId}`, {
    method: 'PATCH',
    body: JSON.stringify({ action, reason }),
  })
}

export async function getTriggerHistory(
  triggerId: string,
  limit = 50
): Promise<{ trigger_id: string; entries: TriggerHistoryEntry[] }> {
  return fetchJSON(`${API_BASE}/triggers/${triggerId}/history?limit=${limit}`)
}
