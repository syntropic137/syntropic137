import type { components } from '../generated/api-types'
import { API_BASE, fetchJSON } from './base'

export type InventoryStatus = components['schemas']['SessionInventoryResponse']
export type InventorySummary = components['schemas']['SessionInventorySummary']
export type InventorySnapshot = components['schemas']['InventorySnapshot']
export type InventoryPage = components['schemas']['SessionInventoryPageResponse']
export type InventoryKind = InventoryPage['kind']
export type InventoryItem = InventoryPage['items'][number]
export type InventoryItemKeys = components['schemas']['InventoryItemKeys']
export type InventoryNodeLookup = components['schemas']['SessionInventoryNodeResponse']
export type TranscriptBodyState = components['schemas']['TranscriptBodyState']
export type CaptureRevisionHashes = components['schemas']['CaptureRevisionHashes']

/** Membership narrowing; unset fields match every phase or attempt. */
export interface InventoryFilters {
  phase_id?: string
  attempt_id?: string
}

/** The API maximum; traversal follows `next_cursor`, so no page size truncates. */
export const INVENTORY_PAGE_LIMIT = 500

function runPath(executionId: string): string {
  return `${API_BASE}/executions/${encodeURIComponent(executionId)}/session-inventory`
}

export function getSessionInventory(executionId: string, signal?: AbortSignal): Promise<InventoryStatus> {
  return fetchJSON(runPath(executionId), { signal })
}

/** `cursor` is the opaque server `next_cursor`; null reads the first page. */
export function getSessionInventoryPage(
  executionId: string, snapshotId: string, kind: InventoryKind, cursor: string | null,
  signal?: AbortSignal, filters: InventoryFilters = {}, limit: number = INVENTORY_PAGE_LIMIT,
): Promise<InventoryPage> {
  const query = new URLSearchParams({ limit: String(limit) })
  if (filters.phase_id) query.set('phase_id', filters.phase_id)
  if (filters.attempt_id) query.set('attempt_id', filters.attempt_id)
  if (cursor !== null) query.set('cursor', cursor)
  return fetchJSON(`${runPath(executionId)}/${encodeURIComponent(snapshotId)}/${kind}?${query}`, { signal })
}

/** Resolve an edge endpoint that is not on a loaded page. Unknown keys stay unresolved. */
export function getSessionInventoryNode(
  executionId: string, snapshotId: string, nodeKey: string, signal?: AbortSignal,
): Promise<InventoryNodeLookup> {
  return fetchJSON(`${runPath(executionId)}/${encodeURIComponent(snapshotId)}/nodes/${encodeURIComponent(nodeKey)}`, { signal })
}

export type LocalTranscript = components['schemas']['LocalTranscriptResponse']

export function getLocalTranscript(
  executionId: string, harness: string, nativeId: string, revision: string, signal?: AbortSignal,
): Promise<LocalTranscript> {
  const query = new URLSearchParams({ harness, native_id: nativeId })
  return fetchJSON(`${API_BASE}/executions/${encodeURIComponent(executionId)}/session-transcripts/${encodeURIComponent(revision)}?${query}`, { signal, cache: 'no-store' })
}
