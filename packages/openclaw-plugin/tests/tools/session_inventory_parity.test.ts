/**
 * Parity golden (#1398 row 9): replay the API-generated fixture through this
 * plugin's tool and derive the same digest the API test derived.
 */
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SyntropicClient } from "../../src/client.js";
import { synGetSessionInventory } from "../../src/tools/session_inventory.js";
import { inventoryFieldKeys } from "../../src/types.js";
import type { InventoryGap, InventoryItem, InventoryKind, InventoryNode, InventoryNodeRef } from "../../src/types.js";

interface Exchange { path: string; query: Record<string, string>; status: number; body: Record<string, unknown> }
interface Fixture {
  execution_id: string; phase_filter: string; exchanges: Exchange[];
  expected: Record<string, unknown>; expected_phase: { node_ids: string[]; cross_page_child: string };
}
const fixture = JSON.parse(readFileSync(new URL("../../../../apps/syn-api/tests/fixtures/session_inventory_parity.json", import.meta.url), "utf8")) as Fixture;
const client = new SyntropicClient({ apiUrl: "https://api.example/api/v1" });
const mockFetch = vi.fn();
const KINDS: InventoryKind[] = ["node", "membership", "edge", "capture", "gap", "binding", "retraction"];

function serve(input: string): Response {
  const url = new URL(input);
  const path = url.pathname.replace(/^\/api\/v1/, "");
  const query: Record<string, string> = {};
  for (const [key, value] of url.searchParams) if (key !== "limit") query[key] = value;
  const match = fixture.exchanges.find(e => e.path === path && JSON.stringify(Object.entries(e.query).sort()) === JSON.stringify(Object.entries(query).sort()));
  if (!match) return new Response(JSON.stringify({ detail: `no fixture exchange for ${path} ${JSON.stringify(query)}` }), { status: 599 });
  return new Response(JSON.stringify(match.body), { status: match.status });
}

beforeEach(() => { mockFetch.mockReset(); mockFetch.mockImplementation(async (input: string) => serve(input)); vi.stubGlobal("fetch", mockFetch); });
afterEach(() => vi.unstubAllGlobals());

const namespace = (ref: InventoryNodeRef) => ref.harness == null ? ref.kind : `${ref.kind}:${ref.harness}`;

interface AllResult {
  summary: Record<string, unknown>; complete: boolean; traversal_complete: boolean; snapshot_id: string; revision: string;
  coverage: { state: string }; counts: Record<string, number>;
  sections: Record<InventoryKind, { items: InventoryItem[]; truncated: boolean }>; gaps: InventoryGap[] | null;
}

async function readAll(extra: Record<string, string> = {}): Promise<AllResult> {
  const result = await synGetSessionInventory(client, { execution_id: fixture.execution_id, all: true, ...extra });
  expect(result.isError).toBeUndefined();
  return JSON.parse(result.content) as AllResult;
}

it("derives the API's counts, coverage, revision, gaps and namespaces", async () => {
  const out = await readAll();
  const refs = (out.sections.node.items as InventoryNode[]).map(n => n.ref);
  const namespaces: Record<string, number> = {};
  for (const ref of refs) namespaces[namespace(ref)] = (namespaces[namespace(ref)] ?? 0) + 1;
  const sortedObject = (o: Record<string, number>) => Object.fromEntries(Object.entries(o).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0));
  const key = (gap: { reason: string; node_keys: string[] }) => JSON.stringify([gap.reason, gap.node_keys]);
  const digest = {
    revision: out.revision,
    snapshot_id: out.snapshot_id,
    coverage_state: out.coverage.state,
    complete: out.complete,
    counts: Object.fromEntries(KINDS.map(k => [k, out.counts[k]])),
    traversed: Object.fromEntries(KINDS.map(k => [k, out.sections[k].items.length])),
    distinct_sessions: out.summary["distinct_sessions"],
    platform_sessions: out.summary["platform_sessions"],
    native_transcripts: out.summary["native_transcripts"],
    invocations: out.summary["invocations"],
    namespaces: sortedObject(namespaces),
    node_ids: refs.map(ref => `${namespace(ref)}/${ref.local_id}`).sort(),
    gaps: (out.gaps ?? []).map(g => ({ reason: g.reason, node_keys: [...(g.node_keys ?? [])].sort() }))
      .sort((a, b) => key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0),
    counts_display: out.summary["counts_display"],
    coverage_display: out.summary["coverage_display"],
  };
  expect(digest).toEqual(fixture.expected);
  expect(KINDS.every(k => !out.sections[k].truncated)).toBe(true);
  expect(out.traversal_complete).toBe(true);
});

it("phase filter selects the same sessions and the node lookup resolves the cross-page child", async () => {
  const out = await readAll({ phase_id: fixture.phase_filter });
  const ids = (out.sections.node.items as InventoryNode[]).map(n => `${namespace(n.ref)}/${n.ref.local_id}`).sort();
  expect(ids).toEqual(fixture.expected_phase.node_ids);
  const edge = out.sections.edge.items[0] as { child: InventoryNodeRef };
  expect(`${namespace(edge.child)}/${edge.child.local_id}`).toBe(fixture.expected_phase.cross_page_child);
  const lookupExchange = fixture.exchanges.find(e => e.path.includes("/nodes/"))!;
  const key = lookupExchange.path.split("/").pop()!;
  const lookup = await synGetSessionInventory(client, { execution_id: fixture.execution_id, snapshot_id: out.snapshot_id, node_key: key });
  const node = JSON.parse(lookup.content) as { status: string; node: InventoryNode };
  expect(node.status).toBe("resolved");
  expect(`${namespace(node.node.ref)}/${node.node.ref.local_id}`).toBe(fixture.expected_phase.cross_page_child);
});

function unknownKeys(value: unknown, known: Record<string, true>): string[] {
  return Object.keys(value as object).filter(key => !(key in known));
}

it("handwritten types know every field the API emits (#1182)", () => {
  const status = fixture.exchanges[0]!.body;
  expect(unknownKeys(status, inventoryFieldKeys.SessionInventoryResponse)).toEqual([]);
  const summary = status["summary"] as Record<string, unknown>;
  expect(unknownKeys(summary, inventoryFieldKeys.SessionInventorySummary)).toEqual([]);
  for (const ns of summary["namespaces"] as object[]) expect(unknownKeys(ns, inventoryFieldKeys.SessionInventoryNamespace)).toEqual([]);
  const snapshot = status["snapshot"] as Record<string, unknown>;
  expect(unknownKeys(snapshot, inventoryFieldKeys.InventorySnapshot)).toEqual([]);
  expect(unknownKeys(snapshot["counts"], inventoryFieldKeys.InventoryCounts)).toEqual([]);
  expect(unknownKeys(snapshot["coverage"], inventoryFieldKeys.InventoryCoverage)).toEqual([]);
  const itemKeys: Record<string, Record<string, true>> = {
    node: inventoryFieldKeys.InventoryNode, membership: inventoryFieldKeys.Membership, edge: inventoryFieldKeys.LineageEdge,
    capture: inventoryFieldKeys.CaptureReceipt, gap: inventoryFieldKeys.InventoryGap, binding: inventoryFieldKeys.IdentityBinding,
    retraction: inventoryFieldKeys.EvidenceRetraction,
  };
  for (const exchange of fixture.exchanges) {
    if (exchange.path.includes("/nodes/")) {
      expect(unknownKeys(exchange.body, inventoryFieldKeys.SessionInventoryNodeResponse)).toEqual([]);
      continue;
    }
    if (!("items" in exchange.body)) continue;
    expect(unknownKeys(exchange.body, inventoryFieldKeys.SessionInventoryPageResponse)).toEqual([]);
    const kind = exchange.body["kind"] as string;
    for (const item of exchange.body["items"] as object[]) {
      expect(unknownKeys(item, itemKeys[kind]!)).toEqual([]);
      if ("ref" in item) expect(unknownKeys(item.ref, inventoryFieldKeys.InventoryNodeRef)).toEqual([]);
    }
  }
});
