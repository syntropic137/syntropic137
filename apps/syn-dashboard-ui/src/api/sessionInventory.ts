import type { components } from '../generated/api-types'
import { API_BASE, fetchJSON } from './base'

export type InventoryStatus = components['schemas']['SessionInventoryResponse']
export type InventoryPage = components['schemas']['SessionInventoryPageResponse']
export type InventoryKind = InventoryPage['kind']

export function getSessionInventory(executionId: string, signal?: AbortSignal): Promise<InventoryStatus> {
  return fetchJSON(`${API_BASE}/executions/${encodeURIComponent(executionId)}/session-inventory`, { signal })
}

export function getSessionInventoryPage(
  executionId: string, snapshotId: string, kind: InventoryKind, after: number, signal?: AbortSignal,
): Promise<InventoryPage> {
  return fetchJSON(`${API_BASE}/executions/${encodeURIComponent(executionId)}/session-inventory/${encodeURIComponent(snapshotId)}/${kind}?after=${after}&limit=100`, { signal })
}

export type LocalTranscript = components['schemas']['LocalTranscriptResponse']

export function getLocalTranscript(
  executionId: string, harness: string, nativeId: string, revision: string, signal?: AbortSignal,
): Promise<LocalTranscript> {
  const query = new URLSearchParams({ harness, native_id: nativeId })
  return fetchJSON(`${API_BASE}/executions/${encodeURIComponent(executionId)}/session-transcripts/${encodeURIComponent(revision)}?${query}`, { signal, cache: 'no-store' })
}
