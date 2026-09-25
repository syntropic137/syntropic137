import type { components } from '../generated/api-types'
import { API_BASE, fetchJSON } from './base'

export type InventoryStatus = components['schemas']['SessionInventoryResponse']
export type InventoryPage = components['schemas']['SessionInventoryPageResponse']
export type InventoryKind = InventoryPage['kind']

export function getSessionInventory(executionId: string, signal?: AbortSignal): Promise<InventoryStatus> {
  return fetchJSON(`${API_BASE}/executions/${encodeURIComponent(executionId)}/session-inventory`, { signal })
}

/** `cursor` is the opaque server `next_cursor`; null reads the first page. */
export function getSessionInventoryPage(
  executionId: string, snapshotId: string, kind: InventoryKind, cursor: string | null, signal?: AbortSignal,
): Promise<InventoryPage> {
  const query = new URLSearchParams({ limit: '100' })
  if (cursor !== null) query.set('cursor', cursor)
  return fetchJSON(`${API_BASE}/executions/${encodeURIComponent(executionId)}/session-inventory/${encodeURIComponent(snapshotId)}/${kind}?${query}`, { signal })
}

export type LocalTranscript = components['schemas']['LocalTranscriptResponse']

export function getLocalTranscript(
  executionId: string, harness: string, nativeId: string, revision: string, signal?: AbortSignal,
): Promise<LocalTranscript> {
  const query = new URLSearchParams({ harness, native_id: nativeId })
  return fetchJSON(`${API_BASE}/executions/${encodeURIComponent(executionId)}/session-transcripts/${encodeURIComponent(revision)}?${query}`, { signal, cache: 'no-store' })
}
