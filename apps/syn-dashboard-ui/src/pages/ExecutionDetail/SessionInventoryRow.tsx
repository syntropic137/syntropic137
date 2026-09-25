import { useState, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'

import { getSessionInventoryNode, type InventoryNodeLookup } from '../../api/sessionInventory'
import {
  namespaceOf, platformSessionHref,
  type LineageLink, type SessionRow,
} from '../../utils/sessionInventoryView'
import { LocalTranscript } from './LocalTranscript'

export interface RowContext {
  executionId: string
  snapshotId: string
  loadedKeys: ReadonlySet<string>
  copy: (id: string, text: string) => void
  lastCopied: string | null
}

type Lookup = { state: 'loading' } | { state: 'done'; result: InventoryNodeLookup } | { state: 'failed'; message: string }

function SessionId({ row, context, copyId }: { row: SessionRow; context: RowContext; copyId: string }) {
  const href = platformSessionHref(row.ref)
  return <div className="si-id-line">
    <span className={`si-badge si-badge-${row.ref.kind}`}>{namespaceOf(row.ref)}</span>
    {href
      ? <Link className="si-id" to={href}>{row.ref.local_id}</Link>
      : <code className="si-id">{row.ref.local_id}</code>}
    <button type="button" className="si-button" tabIndex={-1}
      aria-label={`Copy ${namespaceOf(row.ref)} ID ${row.ref.local_id}`}
      onClick={() => context.copy(copyId, row.ref.local_id)}>
      {context.lastCopied === copyId ? 'Copied' : 'Copy ID'}
    </button>
  </div>
}

function Details({ row }: { row: SessionRow }) {
  const phases = row.memberships.map(m => `${m.phase_id ?? 'unassigned phase'} / ${m.attempt_id ?? 'unknown attempt'}`)
  return <dl className="si-details">
    <dt>Harness</dt><dd>{row.ref.harness ?? (row.ref.kind === 'platform' ? 'platform session' : 'registered invocation')}</dd>
    <dt>Phase attempt</dt><dd>{phases.length ? phases.join(', ') : 'none (unlinked)'}</dd>
    <dt>Parent</dt><dd>{row.parents.length ? row.parents.map(p => `${p.relation} from ${namespaceOf(p.ref)} ${p.ref.local_id}`).join(', ') : 'none'}</dd>
    <dt>Local transcript</dt><dd>{row.capture.local ? `recorded ${row.capture.local}${row.capture.current ? `; now ${row.capture.current}` : ''}` : 'no local receipt'}</dd>
    <dt>Replication</dt><dd>{row.capture.replication.replace('_', ' ')}{row.capture.remoteCurrent ? `; replica now ${row.capture.remoteCurrent}` : ''}</dd>
    {row.capture.hashes.map(hash => <FragmentHash key={`${hash.label}:${hash.value}`} label={hash.label} value={hash.value} />)}
    {row.bindings.map(binding => <FragmentBinding key={`${binding.role}:${namespaceOf(binding.ref)}:${binding.ref.local_id}`} binding={binding} />)}
  </dl>
}

function FragmentHash({ label, value }: { label: string; value: string }) {
  return <><dt>{label}</dt><dd><code className="si-id">{value}</code></dd></>
}

function FragmentBinding({ binding }: { binding: SessionRow['bindings'][number] }) {
  return <>
    <dt>{binding.role === 'owner' ? 'Represented by' : 'Native transcript'}</dt>
    <dd><span className="si-muted">{namespaceOf(binding.ref)}</span> <code className="si-id">{binding.ref.local_id}</code> ({binding.confidence})</dd>
  </>
}

function LineageChild({ link, lookup }: { link: LineageLink; lookup: Lookup | undefined }) {
  let where = 'in this view'
  if (lookup?.state === 'loading') where = 'resolving...'
  else if (lookup?.state === 'failed') where = `lookup failed: ${lookup.message}`
  else if (lookup?.state === 'done') where = lookup.result.status === 'resolved' ? 'in this revision, not loaded here (filtered out or not yet paged in)' : 'not in this revision'
  const href = platformSessionHref(link.ref)
  return <li>
    {link.relation} ({link.confidence}): <span className="si-muted">{namespaceOf(link.ref)}</span>{' '}
    {href ? <Link className="si-id" to={href} tabIndex={-1}>{link.ref.local_id}</Link> : <code className="si-id">{link.ref.local_id}</code>}
    {' '}<span className="si-muted">[{where}]</span>
  </li>
}

function useLineageLookups(context: RowContext, children: LineageLink[]) {
  const [lookups, setLookups] = useState<Record<string, Lookup>>({})
  function resolve() {
    for (const child of children) {
      const key = child.key
      if (!key || context.loadedKeys.has(key) || lookups[key]) continue
      setLookups(prev => ({ ...prev, [key]: { state: 'loading' } }))
      getSessionInventoryNode(context.executionId, context.snapshotId, key)
        .then(result => setLookups(prev => ({ ...prev, [key]: { state: 'done', result } })))
        .catch(reason => setLookups(prev => ({ ...prev, [key]: { state: 'failed', message: reason instanceof Error ? reason.message : 'unavailable' } })))
    }
  }
  return { lookups, resolve }
}

function RowTranscript({ row, context }: { row: SessionRow; context: RowContext }) {
  const hash = row.capture.openable?.archived_byte_hash
  if (!hash || !row.ref.harness) return null
  return <LocalTranscript
    key={JSON.stringify([context.executionId, row.ref.source_instance_id, row.ref.harness, row.ref.local_id, hash])}
    executionId={context.executionId} harness={row.ref.harness} nativeId={row.ref.local_id} revision={hash} />
}

function RowLineage({ row, expanded, lookups, onToggle }: {
  row: SessionRow; expanded: boolean; lookups: Record<string, Lookup>; onToggle: () => void
}) {
  if (row.children.length === 0) return null
  return <>
    <button type="button" className="si-button" tabIndex={-1} aria-expanded={expanded} onClick={onToggle}>
      {expanded ? 'Hide' : 'Show'} lineage ({row.children.length})
    </button>
    {expanded && <ul className="si-lineage" aria-label={`Lineage of ${row.ref.local_id}`}>
      {row.children.map((child, index) => <LineageChild key={`${child.key ?? index}`} link={child} lookup={child.key ? lookups[child.key] : undefined} />)}
    </ul>}
  </>
}

function toggleOnKey(event: KeyboardEvent<HTMLLIElement>, toggle: () => void): void {
  if (event.target !== event.currentTarget) return
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  toggle()
}

export function SessionInventoryRow({ row, rowId, active, context, onFocusRow }: {
  row: SessionRow; rowId: string; active: boolean; context: RowContext; onFocusRow: (rowId: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const { lookups, resolve } = useLineageLookups(context, row.children)
  function toggle() {
    if (!expanded) resolve()
    setExpanded(value => !value)
  }
  return <li className="si-row" data-inventory-row={rowId} tabIndex={active ? 0 : -1}
    aria-expanded={row.children.length ? expanded : undefined}
    onFocus={() => onFocusRow(rowId)}
    onKeyDown={event => toggleOnKey(event, toggle)}>
    <SessionId row={row} context={context} copyId={`session:${rowId}`} />
    <Details row={row} />
    <RowLineage row={row} expanded={expanded} lookups={lookups} onToggle={toggle} />
    <RowTranscript row={row} context={context} />
  </li>
}
