import { LocalTranscript } from "./LocalTranscript"
import { useEffect, useState } from 'react'
import {
  getSessionInventory, getSessionInventoryPage,
  type InventoryKind, type InventoryPage, type InventoryStatus,
} from '../../api/sessionInventory'

const sections: { kind: InventoryKind; label: string }[] = [
  { kind: 'node', label: 'Sessions' }, { kind: 'membership', label: 'Run memberships' },
  { kind: 'edge', label: 'Relationships' }, { kind: 'capture', label: 'Transcript captures' },
  { kind: 'gap', label: 'Gaps' }, { kind: 'binding', label: 'Identity bindings' },
  { kind: 'retraction', label: 'Corrections' },
]

type Capture = Extract<InventoryPage['items'][number], { availability: unknown }>

function CaptureItem({ item, executionId, current }: { item: Capture; executionId: string; current?: string }) {
  return <>
    <code className="break-all">{item.node.local_id}</code>
    <p>{item.destination ?? 'local'} availability recorded at capture: {item.availability}</p>
    {current && <p>Current local body: {current}</p>}
    {item.transcript_revision && <p className="break-all">Transcript revision: {item.transcript_revision}</p>}
    {!current && (item.destination ?? 'local') === 'local' && item.archived_byte_hash && item.node.harness && <LocalTranscript
      key={JSON.stringify([executionId, item.node.source_instance_id, item.node.harness, item.node.local_id, item.archived_byte_hash])} executionId={executionId} harness={item.node.harness}
      nativeId={item.node.local_id} revision={item.archived_byte_hash} />}
  </>
}

function InventoryItem({ item, executionId, bodyOverrides }: { item: InventoryPage['items'][number]; executionId: string; bodyOverrides: InventoryPage['body_overrides'] }) {
  if ('ref' in item) return <>
    <span>{item.ref.kind} {item.ref.harness ?? ''}</span>
    <code className="block break-all select-all">{item.ref.local_id}</code>
    <small>Source: {item.ref.source_instance_id}</small>
  </>
  if ('parent' in item) return <>
    <p>{item.relation}: {item.confidence}</p>
    <p className="break-all">Parent: <code>{item.parent.local_id}</code></p>
    <p className="break-all">Child: <code>{item.child.local_id}</code></p>
  </>
  if ('availability' in item) return <CaptureItem item={item} executionId={executionId} current={item.destination === 'local' ? bodyOverrides?.find(state => state.archive_sha256 === item.archived_byte_hash)?.status : undefined} />
  if ('run' in item) return <>
    <code className="break-all">{item.node.local_id}</code>
    <p>Phase: {item.phase_id ?? 'Unassigned'}. Attempt: {item.attempt_id ?? 'Unknown'}. Confidence: {item.confidence}.</p>
    {item.segment && <p>Segment: {item.segment}</p>}
  </>
  if ('owner' in item) return <>
    <p className="break-all">{item.owner.kind}: <code>{item.owner.local_id}</code></p>
    <p className="break-all">{item.transcript.harness}: <code>{item.transcript.local_id}</code></p>
    <p>Confidence: {item.confidence}</p>
  </>
  if ('reason' in item) return <>
    <p className="break-all">{item.reason}</p>
    <p>Affected sessions: {item.node_keys?.length ?? 0}. Supporting observations: {item.evidence_ids?.length ?? 0}.</p>
  </>
  return <p className="break-all">Observation {item.target.evidence_id} corrected by {item.evidence.evidence_id}.</p>
}

function InventoryRows({ page }: { page: InventoryPage }) {
  if (page.items.length === 0) return <p>No {sections.find(s => s.kind === page.kind)?.label.toLowerCase()} in this revision.</p>
  return <ul className="space-y-2">
    {page.items.map((item, index) => <li key={index} className="rounded border border-[var(--color-border)] p-3">
      <InventoryItem item={item} executionId={page.snapshot.run.execution_id} bodyOverrides={page.body_overrides} />
    </li>)}
  </ul>
}

interface InventoryUpdates {
  setStatus: (value: InventoryStatus | null) => void
  setPage: (value: InventoryPage | null) => void
  setLoading: (value: boolean) => void
  setError: (value: string | null) => void
}

function reportReadError(reason: unknown, controller: AbortController, updates: InventoryUpdates) {
  if (controller.signal.aborted) return
  updates.setPage(null)
  updates.setStatus(null)
  updates.setError(reason instanceof Error ? reason.message : 'Unable to load session inventory')
  updates.setLoading(false)
}

async function loadStatus(executionId: string, controller: AbortController, updates: InventoryUpdates) {
  try {
    const result = await getSessionInventory(executionId, controller.signal)
    if (controller.signal.aborted) return
    updates.setStatus(result)
    if (!result.snapshot) updates.setLoading(false)
  } catch (reason) { reportReadError(reason, controller, updates) }
}

async function loadPage(status: InventoryStatus, kind: InventoryKind, after: number, controller: AbortController, updates: InventoryUpdates) {
  if (!status.snapshot) return
  try {
    const result = await getSessionInventoryPage(status.run.execution_id, status.snapshot.snapshot_id, kind, after, controller.signal)
    if (controller.signal.aborted) return
    if (result.snapshot.snapshot_id !== status.snapshot.snapshot_id) throw new Error('Inventory revision changed; load the latest revision')
    updates.setPage(result)
    updates.setLoading(false)
  } catch (reason) { reportReadError(reason, controller, updates) }
}

function InventorySummary({ status }: { status: InventoryStatus }) {
  return <>
    <p>Reconstruction: {status.reconstruction_status}. Coverage: {status.snapshot?.coverage.state ?? 'unknown'}.
      {status.later_evidence_pending && ' New evidence is awaiting reconstruction.'}</p>
    {!status.snapshot && <p>No published inventory yet.</p>}
    {status.snapshot && <p className="text-sm break-all">Revision: {status.snapshot.revision}. Evidence watermark: {status.snapshot.evidence_watermark}.</p>}
  </>
}

function InventoryPagination({ loading, page, after, onPage }: {
  loading: boolean; page: InventoryPage | null; after: number; onPage: (after: number) => void
}) {
  if (loading) return null
  const next = page?.next_after
  return <>
    {next != null && <button type="button" onClick={() => onPage(next)}>Next page</button>}
    {after >= 0 && <button type="button" onClick={() => onPage(-1)}>First page</button>}
  </>
}

/** Bounded reads remain pinned until the user explicitly loads the latest revision. */
export function SessionInventory({ executionId }: { executionId: string }) {
  const [status, setStatus] = useState<InventoryStatus | null>(null)
  const [page, setPage] = useState<InventoryPage | null>(null)
  const [kind, setKind] = useState<InventoryKind>('node')
  const [after, setAfter] = useState(-1)
  const [reload, setReload] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    void loadStatus(executionId, controller, { setStatus, setPage, setLoading, setError })
    return () => controller.abort()
  }, [executionId, reload])

  useEffect(() => {
    if (!status?.snapshot) return
    const controller = new AbortController()
    void loadPage(status, kind, after, controller, { setStatus, setPage, setLoading, setError })
    return () => controller.abort()
  }, [status, kind, after])

  function loadLatest() {
    setStatus(null); setPage(null); setError(null); setAfter(-1); setLoading(true)
    setReload(value => value + 1)
  }

  return <section aria-label="Session inventory" className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 space-y-3">
    <div className="flex items-center justify-between gap-3">
      <h2 className="font-semibold">Session inventory</h2>
      <button type="button" disabled={loading} onClick={loadLatest}>Load latest revision</button>
    </div>
    {error && <p role="alert">{error}</p>}
    {status && <InventorySummary status={status} />}
    {status?.snapshot && <>
      <label>Show <select aria-label="Inventory section" value={kind} disabled={loading} onChange={event => {
        setKind(event.target.value as InventoryKind); setAfter(-1); setPage(null); setError(null); setLoading(true)
      }}>
        {sections.map(section => <option key={section.kind} value={section.kind}>{section.label} ({status.snapshot!.counts[section.kind] ?? 0})</option>)}
      </select></label>
    </>}
    {loading && <p role="status">Loading session inventory...</p>}
    {!loading && page && <InventoryRows page={page} />}
    <InventoryPagination loading={loading} page={page} after={after} onPage={value => {
      setAfter(value); setPage(null); setLoading(true); setError(null)
    }} />
  </section>
}
