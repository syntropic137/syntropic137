/**
 * Read one pinned inventory revision within a bounded item budget.
 *
 * Every read is pinned to the snapshot the status read returned, so counts,
 * gaps and lineage come from one revision. A load stops once its budget is
 * spent and records each unfinished section's server cursor in `pending`;
 * `continueSessionInventory` resumes exactly there on the same snapshot. A
 * cursor is never dropped, so a truncated read is always visibly incomplete.
 */
import {
  INVENTORY_PAGE_LIMIT, getSessionInventory, getSessionInventoryPage,
  type CaptureRevisionHashes, type InventoryFilters, type InventoryItem, type InventoryItemKeys, type InventoryKind,
  type InventorySnapshot, type InventoryStatus, type TranscriptBodyState,
} from './sessionInventory'

export const INVENTORY_KINDS: readonly InventoryKind[] = ['node', 'membership', 'edge', 'capture', 'gap', 'binding', 'retraction']

/** Items one load (or one continuation) may add: about ten full pages. */
export const DEFAULT_INVENTORY_BUDGET = 5000

export interface KeyedItem {
  item: InventoryItem
  keys: InventoryItemKeys
  /** Capture pages only: names the representation behind each receipt's hashes. */
  hashes?: CaptureRevisionHashes
}

export type InventorySections = Record<InventoryKind, KeyedItem[]>

/** Unfinished sections: the server cursor to resume from, or null when the section has not started. */
export type PendingSections = Partial<Record<InventoryKind, string | null>>

export interface InventoryData {
  status: InventoryStatus
  /** Null when no revision is published yet; sections are then empty. */
  snapshot: InventorySnapshot | null
  filters: InventoryFilters
  sections: InventorySections
  bodyOverrides: TranscriptBodyState[]
  pending: PendingSections
}

function emptySections(): InventorySections {
  return { node: [], membership: [], edge: [], capture: [], gap: [], binding: [], retraction: [] }
}

export function hasPending(data: InventoryData): boolean {
  return Object.keys(data.pending).length > 0
}

interface ReadContext {
  data: InventoryData
  snapshot: InventorySnapshot
  signal: AbortSignal | undefined
  remaining: number
}

async function readPage(context: ReadContext, kind: InventoryKind, cursor: string | null): Promise<string | null> {
  const { data, snapshot, signal } = context
  const limit = Math.min(INVENTORY_PAGE_LIMIT, context.remaining)
  const page = await getSessionInventoryPage(data.status.run.execution_id, snapshot.snapshot_id, kind, cursor, signal, data.filters, limit)
  signal?.throwIfAborted()
  if (page.kind !== kind) throw new Error('Inventory response belongs to another section')
  if (page.snapshot.snapshot_id !== snapshot.snapshot_id) throw new Error('Inventory revision changed; load the latest revision')
  page.items.forEach((item, index) => data.sections[kind].push({ item, keys: page.item_keys[index] ?? {}, hashes: page.capture_hashes?.[index] }))
  data.bodyOverrides.push(...(page.body_overrides ?? []))
  context.remaining -= page.items.length
  const next: string | null = page.next_cursor ?? null
  if (next !== null && next === cursor) throw new Error('Inventory cursor did not advance')
  return next
}

/** Read one section from `cursor` until it ends or the budget is spent; returns the resume cursor. */
async function readSection(context: ReadContext, kind: InventoryKind, start: string | null): Promise<string | null | undefined> {
  let cursor = start
  do {
    if (context.remaining <= 0) return cursor
    cursor = await readPage(context, kind, cursor)
  } while (cursor !== null)
  return undefined
}

async function drain(context: ReadContext, sections: PendingSections): Promise<PendingSections> {
  const pending: PendingSections = {}
  for (const kind of INVENTORY_KINDS) {
    if (!(kind in sections)) continue
    const resume = await readSection(context, kind, sections[kind] ?? null)
    if (resume !== undefined) pending[kind] = resume
  }
  return pending
}

export async function loadSessionInventory(
  executionId: string, filters: InventoryFilters = {}, signal?: AbortSignal, budget: number = DEFAULT_INVENTORY_BUDGET,
): Promise<InventoryData> {
  const status = await getSessionInventory(executionId, signal)
  signal?.throwIfAborted()
  const snapshot = status.snapshot ?? null
  const data: InventoryData = { status, snapshot, filters, sections: emptySections(), bodyOverrides: [], pending: {} }
  if (!snapshot) return data
  const all: PendingSections = Object.fromEntries(INVENTORY_KINDS.map(kind => [kind, null]))
  data.pending = await drain({ data, snapshot, signal, remaining: budget }, all)
  return data
}

/** Resume every pending section on the same pinned snapshot, adding at most one more budget. */
export async function continueSessionInventory(
  previous: InventoryData, signal?: AbortSignal, budget: number = DEFAULT_INVENTORY_BUDGET,
): Promise<InventoryData> {
  const snapshot = previous.snapshot
  if (!snapshot || !hasPending(previous)) return previous
  const data: InventoryData = {
    ...previous,
    sections: Object.fromEntries(INVENTORY_KINDS.map(kind => [kind, [...previous.sections[kind]]])) as InventorySections,
    bodyOverrides: [...previous.bodyOverrides],
    pending: {},
  }
  data.pending = await drain({ data, snapshot, signal, remaining: budget }, previous.pending)
  return data
}
