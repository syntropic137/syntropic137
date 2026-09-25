import './SessionInventory.css'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'

import type { InventoryFilters } from '../../api/sessionInventory'
import type { InventoryData } from '../../api/sessionInventoryTraversal'
import { useCopyFeedback } from '../../hooks/useCopyFeedback'
import { useSessionInventory, type SessionInventoryState } from '../../hooks/useSessionInventory'
import {
  INVENTORY_ATTEMPT_PARAM, INVENTORY_PHASE_PARAM, SESSION_INVENTORY_ANCHOR,
} from '../../utils/sessionInventoryLinks'
import { buildInventoryView, runIdentityText, type SessionRow } from '../../utils/sessionInventoryView'
import { SessionInventoryRow, type RowContext } from './SessionInventoryRow'

const ROWS_PER_GROUP = 50

function useInventoryFilters(): [InventoryFilters, (next: InventoryFilters) => void] {
  const [params, setParams] = useSearchParams()
  const filters: InventoryFilters = {
    phase_id: params.get(INVENTORY_PHASE_PARAM) || undefined,
    attempt_id: params.get(INVENTORY_ATTEMPT_PARAM) || undefined,
  }
  function update(next: InventoryFilters) {
    setParams(prev => {
      const copy = new URLSearchParams(prev)
      for (const [param, value] of [[INVENTORY_PHASE_PARAM, next.phase_id], [INVENTORY_ATTEMPT_PARAM, next.attempt_id]] as const) {
        if (value) copy.set(param, value)
        else copy.delete(param)
      }
      return copy
    }, { replace: true })
  }
  return [filters, update]
}

function Summary({ data }: { data: InventoryData }) {
  const { summary } = data.status
  const count = (value: number | null) => value ?? 'not recorded'
  return <div className="si-summary">
    <p>{summary.counts_display}</p>
    <dl className="si-counts">
      <dt>Platform sessions</dt><dd>{count(summary.platform_sessions)}</dd>
      <dt>Native transcripts</dt><dd>{count(summary.native_transcripts)}</dd>
      <dt>Invocations</dt><dd>{count(summary.invocations)}</dd>
      <dt>Gaps</dt><dd>{count(summary.gaps)}</dd>
    </dl>
    <p>Coverage: {summary.coverage_display}. Reconstruction: {data.status.reconstruction_status.replace('_', ' ')}.</p>
    {summary.revision && <p className="si-muted si-wrap">Revision: {summary.revision}</p>}
  </div>
}

function Notices({ data }: { data: InventoryData }) {
  const { summary } = data.status
  return <>
    {summary.coverage_state === 'unsupported'
      ? <p className="si-notice si-notice-warn" data-state="unsupported">Unsupported: completeness cannot be proven for this run's harness. Listed sessions are real; others may exist.</p>
      : !summary.complete && data.snapshot && <p className="si-notice si-notice-warn" data-state="partial">Partial inventory: {summary.coverage_display}.</p>}
    {summary.complete && <p className="si-notice si-notice-ok" data-state="complete">Complete: every expected session is accounted for.</p>}
    {data.status.later_evidence_pending && <p className="si-notice" data-state="pending">New evidence is awaiting reconstruction; load the latest revision later.</p>}
    {summary.remote_replication === 'disabled' && <p className="si-notice" data-state="remote-disabled">Remote replication is disabled. Local capture and this inventory are unaffected.</p>}
  </>
}

function FilterControls({ filters, onChange }: { filters: InventoryFilters; onChange: (next: InventoryFilters) => void }) {
  const [phase, setPhase] = useState(filters.phase_id ?? '')
  const [attempt, setAttempt] = useState(filters.attempt_id ?? '')
  const active = Boolean(filters.phase_id || filters.attempt_id)
  return <form className="si-filters" onSubmit={event => {
    event.preventDefault()
    onChange({ phase_id: phase.trim() || undefined, attempt_id: attempt.trim() || undefined })
  }}>
    <label>Phase <input value={phase} onChange={event => setPhase(event.target.value)} aria-label="Phase filter" /></label>
    <label>Attempt <input value={attempt} onChange={event => setAttempt(event.target.value)} aria-label="Attempt filter" /></label>
    <button type="submit" className="si-button">Apply filter</button>
    {active && <button type="button" className="si-button" onClick={() => { setPhase(''); setAttempt(''); onChange({}) }}>Clear filter</button>}
  </form>
}

function GroupRows({ rows, groupId, context, activeRow, onFocusRow }: {
  rows: SessionRow[]; groupId: string; context: RowContext; activeRow: string | null; onFocusRow: (id: string) => void
}) {
  const [shown, setShown] = useState(ROWS_PER_GROUP)
  return <>
    <ul className="si-rows">
      {rows.slice(0, shown).map(row => {
        const rowId = `${groupId}|${row.key}`
        return <SessionInventoryRow key={rowId} row={row} rowId={rowId} active={activeRow === rowId} context={context} onFocusRow={onFocusRow} />
      })}
    </ul>
    {rows.length > shown && <button type="button" className="si-button" onClick={() => setShown(value => value + ROWS_PER_GROUP)}>
      Show more ({rows.length - shown} remaining)
    </button>}
  </>
}

function moveFocus(event: KeyboardEvent<HTMLDivElement>) {
  const keys = ['ArrowDown', 'ArrowUp', 'Home', 'End']
  if (!keys.includes(event.key)) return
  const rows = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[data-inventory-row]'))
  if (rows.length === 0) return
  const current = rows.findIndex(row => row === document.activeElement || row.contains(document.activeElement))
  let next = current
  if (event.key === 'ArrowDown') next = Math.min(rows.length - 1, current + 1)
  if (event.key === 'ArrowUp') next = Math.max(0, current - 1)
  if (event.key === 'Home') next = 0
  if (event.key === 'End') next = rows.length - 1
  event.preventDefault()
  rows[next]?.focus()
}

function InventoryBody({ data, onFilter }: { data: InventoryData; onFilter: (next: InventoryFilters) => void }) {
  const view = useMemo(() => buildInventoryView(data), [data])
  const { lastCopied, copy } = useCopyFeedback<string>()
  const [focused, setFocused] = useState<string | null>(null)
  const firstRow = view.groups[0] ? `${view.groups[0].id}|${view.groups[0].rows[0]?.key}` : view.unlinked[0] ? `unlinked|${view.unlinked[0].key}` : null
  const activeRow = focused ?? firstRow
  const context: RowContext = {
    executionId: data.status.run.execution_id,
    snapshotId: data.snapshot?.snapshot_id ?? '',
    loadedKeys: new Set(view.rowsByKey.keys()),
    copy: (id, text) => { void copy(id, text) },
    lastCopied,
  }
  return <>
    <div className="si-actions">
      <button type="button" className="si-button" onClick={() => void copy('run', runIdentityText(data))}>
        {lastCopied === 'run' ? 'Copied' : 'Copy run identity'}
      </button>
      <button type="button" className="si-button" onClick={() => void copy('execution', data.status.run.execution_id)}>
        {lastCopied === 'execution' ? 'Copied' : 'Copy execution ID'}
      </button>
    </div>
    <div className="si-groups" onKeyDown={moveFocus} aria-label="Sessions by phase and attempt">
      {view.groups.map(group => <section key={group.id} className="si-group" aria-label={`Phase ${group.phase_id ?? 'unassigned'} attempt ${group.attempt_id ?? 'unknown'}`}>
        <header className="si-group-header">
          <h3>Phase {group.phase_id ?? 'unassigned'} <span className="si-muted">attempt {group.attempt_id ?? 'unknown'}</span> ({group.rows.length})</h3>
          {!(data.filters.phase_id === (group.phase_id ?? undefined) && data.filters.attempt_id === (group.attempt_id ?? undefined)) && group.phase_id &&
            <button type="button" className="si-button" onClick={() => onFilter({ phase_id: group.phase_id ?? undefined, attempt_id: group.attempt_id ?? undefined })}>Only this attempt</button>}
        </header>
        <GroupRows rows={group.rows} groupId={group.id} context={context} activeRow={activeRow} onFocusRow={setFocused} />
      </section>)}
      {view.unlinked.length > 0 && <section className="si-group" aria-label="Unlinked sessions">
        <header className="si-group-header"><h3>Unbound or unlinked ({view.unlinked.length})</h3></header>
        <p className="si-muted">Sessions discovered in this run with no phase or attempt membership.</p>
        <GroupRows rows={view.unlinked} groupId="unlinked" context={context} activeRow={activeRow} onFocusRow={setFocused} />
      </section>}
    </div>
    {view.gaps.length > 0 && <section className="si-group" aria-label="Inventory gaps">
      <h3>Gaps ({view.gaps.length})</h3>
      <ul className="si-rows">{view.gaps.map((gap, index) => <li key={index} className="si-row si-wrap">
        {gap.reason} <span className="si-muted">affects {gap.node_keys?.length ?? 0} sessions; {gap.evidence_ids?.length ?? 0} observations</span>
      </li>)}</ul>
    </section>}
  </>
}

function StateView({ state, onFilter }: { state: SessionInventoryState; onFilter: (next: InventoryFilters) => void }) {
  switch (state.kind) {
    case 'loading': return <p role="status">Loading session inventory...</p>
    case 'permission_denied': return <p role="alert" data-state="permission-denied">Permission denied: {state.message}</p>
    case 'expired': return <p role="alert" data-state="expired">This inventory revision expired. Load the latest revision. ({state.message})</p>
    case 'error': return <p role="alert" data-state="error">{state.message}</p>
    case 'not_published': return <>
      <p data-state="not-published">No published inventory yet. Reconstruction: {state.data.status.reconstruction_status.replace('_', ' ')}.</p>
      <Notices data={state.data} />
    </>
    case 'empty': return <>
      <Summary data={state.data} />
      <Notices data={state.data} />
      <p data-state="empty">No sessions {state.data.filters.phase_id || state.data.filters.attempt_id ? 'match this filter' : 'in this revision'}.</p>
    </>
    case 'ready': return <>
      <Summary data={state.data} />
      <Notices data={state.data} />
      <InventoryBody data={state.data} onFilter={onFilter} />
    </>
  }
}

/** All sessions of one pinned revision, grouped by phase/attempt. Reads never trigger reconstruction. */
export function SessionInventory({ executionId }: { executionId: string }) {
  const [filters, setFilters] = useInventoryFilters()
  const { state, reload } = useSessionInventory(executionId, filters)
  const sectionRef = useRef<HTMLElement>(null)
  const location = useLocation()
  useEffect(() => {
    if (location.hash === `#${SESSION_INVENTORY_ANCHOR}`) sectionRef.current?.scrollIntoView?.({ block: 'start' })
  }, [location.hash])
  return <section id={SESSION_INVENTORY_ANCHOR} ref={sectionRef} aria-label="Session inventory" className="si-panel">
    <div className="si-header">
      <h2>Sessions</h2>
      <button type="button" className="si-button" disabled={state.kind === 'loading'} onClick={reload}>Load latest revision</button>
    </div>
    <FilterControls key={`${filters.phase_id ?? ''}\u0000${filters.attempt_id ?? ''}`} filters={filters} onChange={setFilters} />
    <StateView state={state} onFilter={setFilters} />
  </section>
}
