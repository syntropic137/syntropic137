/**
 * Read every page of every section of ONE pinned inventory revision.
 *
 * The dashboard never shows a first page as if it were the inventory: all
 * sections are followed to `next_cursor === null` against the snapshot the
 * status read returned, so counts, gaps and lineage come from the same revision.
 */
import {
  getSessionInventory, getSessionInventoryPage,
  type InventoryFilters, type InventoryItem, type InventoryItemKeys, type InventoryKind,
  type InventorySnapshot, type InventoryStatus, type TranscriptBodyState,
} from './sessionInventory'

export const INVENTORY_KINDS: readonly InventoryKind[] = ['node', 'membership', 'edge', 'capture', 'gap', 'binding', 'retraction']

export interface KeyedItem {
  item: InventoryItem
  keys: InventoryItemKeys
}

export type InventorySections = Record<InventoryKind, KeyedItem[]>

export interface InventoryData {
  status: InventoryStatus
  /** Null when no revision is published yet; sections are then empty. */
  snapshot: InventorySnapshot | null
  filters: InventoryFilters
  sections: InventorySections
  bodyOverrides: TranscriptBodyState[]
}

function emptySections(): InventorySections {
  return { node: [], membership: [], edge: [], capture: [], gap: [], binding: [], retraction: [] }
}

async function readSection(
  status: InventoryStatus, snapshot: InventorySnapshot, kind: InventoryKind,
  filters: InventoryFilters, signal: AbortSignal | undefined, data: InventoryData,
): Promise<void> {
  let cursor: string | null = null
  do {
    const page = await getSessionInventoryPage(status.run.execution_id, snapshot.snapshot_id, kind, cursor, signal, filters)
    signal?.throwIfAborted()
    if (page.kind !== kind) throw new Error('Inventory response belongs to another section')
    if (page.snapshot.snapshot_id !== snapshot.snapshot_id) throw new Error('Inventory revision changed; load the latest revision')
    page.items.forEach((item, index) => data.sections[kind].push({ item, keys: page.item_keys[index] ?? {} }))
    data.bodyOverrides.push(...(page.body_overrides ?? []))
    const next: string | null = page.next_cursor ?? null
    if (next !== null && next === cursor) throw new Error('Inventory cursor did not advance')
    cursor = next
  } while (cursor !== null)
}

export async function loadSessionInventory(
  executionId: string, filters: InventoryFilters = {}, signal?: AbortSignal,
): Promise<InventoryData> {
  const status = await getSessionInventory(executionId, signal)
  signal?.throwIfAborted()
  const snapshot = status.snapshot ?? null
  const data: InventoryData = { status, snapshot, filters, sections: emptySections(), bodyOverrides: [] }
  if (!snapshot) return data
  for (const kind of INVENTORY_KINDS) await readSection(status, snapshot, kind, filters, signal, data)
  return data
}
