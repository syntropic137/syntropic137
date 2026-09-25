/**
 * Pure projection of a traversed inventory revision into what the Sessions
 * view renders: phase/attempt groups, unlinked sessions, lineage and capture
 * state per session. Counts are never recomputed here; they come from the
 * server summary so every client shows the same numbers.
 */
import type { components } from '../generated/api-types'
import type { InventoryData, KeyedItem } from '../api/sessionInventoryTraversal'

export type NodeRef = components['schemas']['InventoryNodeRef']
type InventoryNode = components['schemas']['InventoryNode']
type Membership = components['schemas']['Membership']
type LineageEdge = components['schemas']['LineageEdge']
type CaptureReceipt = components['schemas']['CaptureReceipt']
type IdentityBinding = components['schemas']['IdentityBinding']
type TranscriptBodyState = components['schemas']['TranscriptBodyState']
export type InventoryGap = components['schemas']['InventoryGap']

export interface LineageLink {
  key: string | null
  ref: NodeRef
  relation: LineageEdge['relation']
  confidence: LineageEdge['confidence']
}

/** One receipt hash under the name of the representation it holds. */
export interface RevisionHash {
  label: string
  value: string
}

export interface CaptureState {
  /** Availability recorded by the latest local receipt, or null if none. */
  local: CaptureReceipt['availability'] | null
  /** Current restriction on the local body (expired/deleted/withheld), separate from the receipt. */
  current: TranscriptBodyState['status'] | null
  /** Current restriction on the replica body, matched by source-content hash. */
  remoteCurrent: TranscriptBodyState['status'] | null
  /** Hashes of the newest receipts, each named by its representation; never compare kinds. */
  hashes: RevisionHash[]
  /** The newest local present receipt a transcript can be opened from. */
  openable: CaptureReceipt | null
  /** Remote replication of this session's transcript. */
  replication: 'replicated' | 'pending' | 'missing' | 'expired' | 'unknown' | 'not_replicated' | 'disabled'
}

export interface SessionRow {
  key: string
  ref: NodeRef
  memberships: Membership[]
  parents: LineageLink[]
  children: LineageLink[]
  /** Platform/invocation owners of a native transcript, or transcripts an owner represents. */
  bindings: { ref: NodeRef; role: 'owner' | 'transcript'; confidence: IdentityBinding['confidence'] }[]
  capture: CaptureState
}

export interface SessionGroup {
  id: string
  phase_id: string | null
  attempt_id: string | null
  rows: SessionRow[]
}

export interface InventoryView {
  groups: SessionGroup[]
  /** Sessions in this revision with no run membership (unbound/unlinked). */
  unlinked: SessionRow[]
  rowsByKey: Map<string, SessionRow>
  gaps: InventoryGap[]
}

export function namespaceOf(ref: NodeRef): string {
  return ref.harness == null ? ref.kind : `${ref.kind}:${ref.harness}`
}

/** Only a platform session id is valid for /sessions/{id}; native and invocation ids never are. */
export function platformSessionHref(ref: NodeRef): string | null {
  return ref.kind === 'platform' ? `/sessions/${encodeURIComponent(ref.local_id)}` : null
}

function isNode(item: KeyedItem['item']): item is InventoryNode { return 'ref' in item }
function isMembership(item: KeyedItem['item']): item is Membership { return 'run' in item && 'node' in item }
function isEdge(item: KeyedItem['item']): item is LineageEdge { return 'parent' in item && 'child' in item }
function isCapture(item: KeyedItem['item']): item is CaptureReceipt { return 'availability' in item }
function isBinding(item: KeyedItem['item']): item is IdentityBinding { return 'owner' in item && 'transcript' in item }
function isGap(item: KeyedItem['item']): item is InventoryGap { return 'reason' in item }

const REVISION_LABELS: Record<string, string> = {
  archived_bytes_sha256: 'Archived bytes SHA-256',
  source_content_hash: 'Source content hash',
  unqualified: 'Transcript revision (unqualified)',
}

/**
 * Current body state matched by the hash the receipt actually carries: archived
 * bytes locally, the APSS source-content hash at a replica. Never cross-matched.
 */
function currentBody(receipt: CaptureReceipt | null, data: InventoryData): TranscriptBodyState['status'] | null {
  if (!receipt) return null
  if ((receipt.destination ?? 'local') === 'local') {
    return receipt.archived_byte_hash
      ? data.bodyOverrides.find(state => state.archive_sha256 === receipt.archived_byte_hash)?.status ?? null
      : null
  }
  const revision = receipt.transcript_revision
  return revision
    ? data.bodyOverrides.find(state => state.source_content_hash != null && state.source_content_hash === revision)?.status ?? null
    : null
}

function revisionHash(entry: CaptureEntry | null): RevisionHash | null {
  if (!entry?.receipt.transcript_revision) return null
  const kind = entry.hashes?.transcript_revision_kind ?? 'unqualified'
  return { label: REVISION_LABELS[kind] ?? REVISION_LABELS.unqualified, value: entry.receipt.transcript_revision }
}

interface CaptureEntry {
  receipt: CaptureReceipt
  hashes: KeyedItem['hashes']
}

function captureState(entries: CaptureEntry[], data: InventoryData): CaptureState {
  const newest = (destination: 'local' | 'remote') => entries
    .filter(e => (e.receipt.destination ?? 'local') === destination)
    .sort((a, b) => b.receipt.receipt_sequence - a.receipt.receipt_sequence)[0] ?? null
  const localEntry = newest('local')
  const remoteEntry = newest('remote')
  const local = localEntry?.receipt ?? null
  const remote = remoteEntry?.receipt ?? null
  const current = currentBody(local, data)
  let replication: CaptureState['replication'] = 'not_replicated'
  if (remote) replication = remote.availability === 'present' ? 'replicated' : remote.availability
  else if (data.status.summary.remote_replication === 'disabled') replication = 'disabled'
  return {
    local: local?.availability ?? null,
    current,
    remoteCurrent: currentBody(remote, data),
    hashes: [revisionHash(localEntry), revisionHash(remoteEntry)].filter((h): h is RevisionHash => h !== null),
    openable: local && local.availability === 'present' && !current && local.archived_byte_hash ? local : null,
    replication,
  }
}

function groupId(phase: string | null, attempt: string | null): string {
  return JSON.stringify([phase, attempt])
}

type RowIndex = Map<string, SessionRow>

function emptyRow(key: string, ref: NodeRef): SessionRow {
  return {
    key, ref, memberships: [], parents: [], children: [], bindings: [],
    capture: { local: null, current: null, remoteCurrent: null, hashes: [], openable: null, replication: 'not_replicated' },
  }
}

function indexNodes(entries: KeyedItem[]): RowIndex {
  const rows: RowIndex = new Map()
  for (const { item, keys } of entries) {
    if (isNode(item) && keys.node_key) rows.set(keys.node_key, emptyRow(keys.node_key, item.ref))
  }
  return rows
}

function attachMemberships(rows: RowIndex, entries: KeyedItem[]): void {
  for (const { item, keys } of entries) {
    if (isMembership(item) && keys.node_key) rows.get(keys.node_key)?.memberships.push(item)
  }
}

function attachEdge(rows: RowIndex, item: LineageEdge, parentKey: string | null, childKey: string | null): void {
  const link = { relation: item.relation, confidence: item.confidence }
  if (parentKey) rows.get(parentKey)?.children.push({ key: childKey, ref: item.child, ...link })
  if (childKey) rows.get(childKey)?.parents.push({ key: parentKey, ref: item.parent, ...link })
}

function attachEdges(rows: RowIndex, entries: KeyedItem[]): void {
  for (const { item, keys } of entries) {
    if (isEdge(item)) attachEdge(rows, item, keys.node_key ?? null, keys.peer_key ?? null)
  }
}

function attachBindings(rows: RowIndex, entries: KeyedItem[]): void {
  for (const { item, keys } of entries) {
    if (!isBinding(item)) continue
    if (keys.node_key) rows.get(keys.node_key)?.bindings.push({ ref: item.transcript, role: 'transcript', confidence: item.confidence })
    if (keys.peer_key) rows.get(keys.peer_key)?.bindings.push({ ref: item.owner, role: 'owner', confidence: item.confidence })
  }
}

function receiptsByNode(entries: KeyedItem[]): Map<string, CaptureEntry[]> {
  const receipts = new Map<string, CaptureEntry[]>()
  for (const { item, keys, hashes } of entries) {
    if (isCapture(item) && keys.node_key) receipts.set(keys.node_key, [...(receipts.get(keys.node_key) ?? []), { receipt: item, hashes }])
  }
  return receipts
}

function addToGroups(groups: Map<string, SessionGroup>, row: SessionRow): void {
  for (const membership of row.memberships) {
    const phase = membership.phase_id ?? null
    const attempt = membership.attempt_id ?? null
    const id = groupId(phase, attempt)
    const group = groups.get(id) ?? { id, phase_id: phase, attempt_id: attempt, rows: [] }
    if (!group.rows.includes(row)) group.rows.push(row)
    groups.set(id, group)
  }
}

const sortKey = (value: string | null) => value ?? '\uffff'

function compareGroups(a: SessionGroup, b: SessionGroup): number {
  return sortKey(a.phase_id).localeCompare(sortKey(b.phase_id)) || sortKey(a.attempt_id).localeCompare(sortKey(b.attempt_id))
}

export function buildInventoryView(data: InventoryData): InventoryView {
  const { sections } = data
  const rowsByKey = indexNodes(sections.node)
  attachMemberships(rowsByKey, sections.membership)
  attachEdges(rowsByKey, sections.edge)
  attachBindings(rowsByKey, sections.binding)
  const receipts = receiptsByNode(sections.capture)
  const groups = new Map<string, SessionGroup>()
  const unlinked: SessionRow[] = []
  for (const row of rowsByKey.values()) {
    row.capture = captureState(receipts.get(row.key) ?? [], data)
    if (row.memberships.length === 0) unlinked.push(row)
    else addToGroups(groups, row)
  }
  return {
    groups: [...groups.values()].sort(compareGroups),
    unlinked,
    rowsByKey,
    gaps: sections.gap.map(entry => entry.item).filter(isGap),
  }
}

/** Machine-readable run identity: everything needed to re-read this exact revision. */
export function runIdentityText(data: InventoryData): string {
  return JSON.stringify({
    source_instance_id: data.status.run.source_instance_id,
    execution_id: data.status.run.execution_id,
    revision: data.snapshot?.revision ?? null,
    snapshot_id: data.snapshot?.snapshot_id ?? null,
  })
}
