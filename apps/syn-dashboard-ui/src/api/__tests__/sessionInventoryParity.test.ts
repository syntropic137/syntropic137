// @vitest-environment node
/**
 * Parity golden (#1398 row 9): the dashboard data layer, replaying the exchanges
 * the real API routes produced, must derive exactly the digest the API test
 * derived. The fixture is regenerated and drift-checked by
 * apps/syn-api/tests/test_session_inventory_parity.py; never hand-edit it.
 */
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { getSessionInventoryNode } from '../sessionInventory'
import { createReplay, fixture } from './inventoryReplay'
import {
  INVENTORY_KINDS, continueSessionInventory, hasPending, loadSessionInventory, type InventoryData,
} from '../sessionInventoryTraversal'
import { buildInventoryView, namespaceOf } from '../../utils/sessionInventoryView'

let replay = createReplay()

beforeEach(() => { replay = createReplay(); vi.stubGlobal('fetch', vi.fn(replay.fetch)) })
afterEach(() => { vi.unstubAllGlobals() })

function digest(data: InventoryData): Record<string, unknown> {
  const snapshot = data.snapshot!
  const { summary } = data.status
  const view = buildInventoryView(data)
  const refs = [...view.rowsByKey.values()].map(row => row.ref)
  const namespaces: Record<string, number> = {}
  for (const ref of refs) namespaces[namespaceOf(ref)] = (namespaces[namespaceOf(ref)] ?? 0) + 1
  const counts = snapshot.counts as unknown as Record<string, number>
  return {
    revision: snapshot.revision,
    snapshot_id: snapshot.snapshot_id,
    coverage_state: snapshot.coverage.state,
    complete: summary.complete,
    counts: Object.fromEntries(INVENTORY_KINDS.map(kind => [kind, counts[kind]])),
    traversed: Object.fromEntries(INVENTORY_KINDS.map(kind => [kind, data.sections[kind].length])),
    distinct_sessions: summary.distinct_sessions,
    platform_sessions: summary.platform_sessions,
    native_transcripts: summary.native_transcripts,
    invocations: summary.invocations,
    namespaces: Object.fromEntries(Object.entries(namespaces).sort(([a], [b]) => a.localeCompare(b))),
    node_ids: refs.map(ref => `${namespaceOf(ref)}/${ref.local_id}`).sort(),
    gaps: view.gaps
      .map(gap => ({ node_keys: [...(gap.node_keys ?? [])].sort(), reason: gap.reason }))
      .sort((a, b) => { const x = JSON.stringify([a.reason, a.node_keys]), y = JSON.stringify([b.reason, b.node_keys]); return x < y ? -1 : x > y ? 1 : 0 }),
    counts_display: summary.counts_display,
    coverage_display: summary.coverage_display,
  }
}

it('derives the same counts, coverage, revision, gaps and namespaces as the API', async () => {
  const data = await loadSessionInventory(fixture.execution_id)
  expect(digest(data)).toEqual(fixture.expected)
})

it('narrows by phase and resolves a cross-page lineage endpoint by node key', async () => {
  const data = await loadSessionInventory(fixture.execution_id, { phase_id: fixture.phase_filter })
  const view = buildInventoryView(data)
  const ids = [...view.rowsByKey.values()].map(row => `${namespaceOf(row.ref)}/${row.ref.local_id}`).sort()
  expect(ids).toEqual(fixture.expected_phase.node_ids)
  const outside = [...view.rowsByKey.values()].flatMap(row => row.children).filter(link => link.key && !view.rowsByKey.has(link.key))
  expect(outside).toHaveLength(1)
  const lookup = await getSessionInventoryNode(fixture.execution_id, data.snapshot!.snapshot_id, outside[0]!.key!)
  expect(lookup.status).toBe('resolved')
  expect(`${namespaceOf(lookup.node!.ref)}/${lookup.node!.ref.local_id}`).toBe(fixture.expected_phase.cross_page_child)
})

it('a tiny budget, continued until nothing is pending, derives the same digest', async () => {
  let data = await loadSessionInventory(fixture.execution_id, {}, undefined, 2)
  expect(hasPending(data)).toBe(true)
  expect(data.sections.node.length).toBeLessThanOrEqual(2)
  for (let round = 0; round < 100 && hasPending(data); round++) {
    const before = INVENTORY_KINDS.reduce((sum, kind) => sum + data.sections[kind].length, 0)
    data = await continueSessionInventory(data, undefined, 2)
    const after = INVENTORY_KINDS.reduce((sum, kind) => sum + data.sections[kind].length, 0)
    expect(after - before).toBeLessThanOrEqual(2)
  }
  expect(hasPending(data)).toBe(false)
  expect(Math.max(...replay.limits)).toBeLessThanOrEqual(2)
  expect(digest(data)).toEqual(fixture.expected)
})
