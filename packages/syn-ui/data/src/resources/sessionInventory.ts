import { request, seg } from '../client'
import type { components } from '../generated/api-types'
import { cached } from '../keys'

export type InventoryStatus = components['schemas']['SessionInventoryResponse']
export type InventorySummary = components['schemas']['SessionInventorySummary']
export type InventorySnapshot = components['schemas']['InventorySnapshot']
export type InventoryPage = components['schemas']['SessionInventoryPageResponse']
export type InventoryKind = InventoryPage['kind']
export type InventoryItem = InventoryPage['items'][number]
export type InventoryNodeLookup = components['schemas']['SessionInventoryNodeResponse']
export type LocalTranscript = components['schemas']['LocalTranscriptResponse']

/** Membership narrowing; unset fields match every phase or attempt. */
export interface InventoryFilters {
  phase_id?: string
  attempt_id?: string
}

/** The API maximum; traversal follows `next_cursor`. */
export const INVENTORY_PAGE_LIMIT = 500

export function getSessionInventory(executionId: string, signal?: AbortSignal): Promise<InventoryStatus> {
  return cached('getSessionInventory', [executionId], (s) => request(`/executions/${seg(executionId)}/session-inventory`, { signal: s }), { signal })
}

/** `cursor` is the opaque server `next_cursor`; null reads the first page. */
export function getSessionInventoryPage(
  executionId: string,
  snapshotId: string,
  kind: InventoryKind,
  cursor: string | null,
  filters: InventoryFilters = {},
  limit: number = INVENTORY_PAGE_LIMIT,
  signal?: AbortSignal,
): Promise<InventoryPage> {
  const query = { limit, phase_id: filters.phase_id, attempt_id: filters.attempt_id, cursor }
  return cached('getSessionInventoryPage', [executionId, snapshotId, kind, query], (s) =>
    request(`/executions/${seg(executionId)}/session-inventory/${seg(snapshotId)}/${kind}`, { query, signal: s }), { signal })
}

export function getSessionInventoryNode(executionId: string, snapshotId: string, nodeKey: string, signal?: AbortSignal): Promise<InventoryNodeLookup> {
  return cached('getSessionInventoryNode', [executionId, snapshotId, nodeKey], (s) =>
    request(`/executions/${seg(executionId)}/session-inventory/${seg(snapshotId)}/nodes/${seg(nodeKey)}`, { signal: s }), { signal })
}

export function getLocalTranscript(
  executionId: string,
  harness: string,
  nativeId: string,
  revision: string,
  signal?: AbortSignal,
): Promise<LocalTranscript> {
  return request(`/executions/${seg(executionId)}/session-transcripts/${seg(revision)}`, {
    query: { harness, native_id: nativeId },
    signal,
    cache: 'no-store',
    coalesce: false,
  })
}
