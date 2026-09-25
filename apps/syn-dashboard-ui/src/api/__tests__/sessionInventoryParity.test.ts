// @vitest-environment node
/**
 * Parity golden (#1398 row 9): the dashboard data layer, replaying the exchanges
 * the real API routes produced, must derive exactly the digest the API test
 * derived. The fixture is regenerated and drift-checked by
 * apps/syn-api/tests/test_session_inventory_parity.py; never hand-edit it.
 */
import { readFileSync } from 'node:fs'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { getSessionInventoryNode } from '../sessionInventory'
import {
  INVENTORY_KINDS, continueSessionInventory, hasPending, loadSessionInventory, type InventoryData,
} from '../sessionInventoryTraversal'
import { buildInventoryView, namespaceOf } from '../../utils/sessionInventoryView'

interface Exchange { path: string; query: Record<string, string>; status: number; body: unknown }
interface Fixture {
  execution_id: string
  phase_filter: string
  exchanges: Exchange[]
  expected: Record<string, unknown>
  expected_phase: { node_ids: string[]; cross_page_child: string }
}

const fixture = JSON.parse(readFileSync(
  new URL('../../../../syn-api/tests/fixtures/session_inventory_parity.json', import.meta.url), 'utf8',
)) as Fixture

function serve(input: RequestInfo | URL): Promise<Response> {
  const url = new URL(String(input), 'http://dashboard.test')
  const path = url.pathname.replace(/^\/api\/v1/, '')
  const query: Record<string, string> = {}
  url.searchParams.forEach((value, name) => { if (name !== 'limit') query[name] = value })
  const match = fixture.exchanges.find(exchange => exchange.path === path
    && JSON.stringify(Object.entries(exchange.query).sort()) === JSON.stringify(Object.entries(query).sort()))
  if (!match) return Promise.resolve(new Response(JSON.stringify({ detail: `unrecorded ${path}` }), { status: 404 }))
  return Promise.resolve(new Response(JSON.stringify(match.body), { status: match.status, headers: { 'Content-Type': 'application/json' } }))
}

beforeEach(() => { vi.stubGlobal('fetch', vi.fn(serve)) })
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
    // The replay ignores `limit` and serves the recorded 2-item pages, so a request
    // for the last budgeted item can return one extra; the real API honors `limit`.
    expect(after - before).toBeLessThanOrEqual(3)
  }
  expect(hasPending(data)).toBe(false)
  expect(digest(data)).toEqual(fixture.expected)
})
