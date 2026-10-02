import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SyntropicClient } from "../../src/client.js";
import { synGetSessionInventory } from "../../src/tools/session_inventory.js";
import { allToolDefs } from "../../src/index.js";

const mockFetch = vi.fn();
const client = new SyntropicClient({ apiUrl: "https://deployment.example/api/v1" });
const snapshot = "11111111-1111-4111-8111-111111111111";
beforeEach(() => { mockFetch.mockReset(); vi.stubGlobal("fetch", mockFetch); });
afterEach(() => vi.unstubAllGlobals());

it("registers the inventory read tool", () => {
  expect(allToolDefs.some(tool => tool.name === "syn_get_session_inventory")).toBe(true);
});

it("preserves explicit pending state without synthesizing an empty inventory", async () => {
  const body = { snapshot: null, reconstruction_status: "pending", later_evidence_pending: true };
  mockFetch.mockResolvedValue(new Response(JSON.stringify(body)));
  const result = await synGetSessionInventory(client, { execution_id: "run" });
  expect(JSON.parse(result.content)).toEqual(body);
  expect(mockFetch.mock.calls[0]![0]).toBe("https://deployment.example/api/v1/executions/run/session-inventory");
});

it("encodes the execution selector and forwards immutable page selectors", async () => {
  const body = { snapshot: { snapshot_id: snapshot }, kind: "edge", items: [], item_keys: [], next_cursor: null };
  mockFetch.mockResolvedValue(new Response(JSON.stringify(body)));
  const result = await synGetSessionInventory(client, { execution_id: "run/unsafe", snapshot_id: snapshot, kind: "edge", cursor: "opaque-cursor", limit: 20 });
  expect(JSON.parse(result.content)).toEqual(body);
  expect(mockFetch.mock.calls[0]![0]).toBe(`https://deployment.example/api/v1/executions/run%2Funsafe/session-inventory/${snapshot}/edge?limit=20&cursor=opaque-cursor`);
});

it("does not fall back to a new snapshot when an old snapshot is unavailable", async () => {
  mockFetch.mockResolvedValue(new Response(JSON.stringify({ detail: "Published inventory not found" }), { status: 404 }));
  const result = await synGetSessionInventory(client, { execution_id: "run", snapshot_id: snapshot });
  expect(result.isError).toBe(true);
  expect(mockFetch).toHaveBeenCalledTimes(1);
});

it("rejects invalid bounds before network access", async () => {
  const result = await synGetSessionInventory(client, { execution_id: "run", snapshot_id: snapshot, limit: 501 });
  expect(result.isError).toBe(true);
  expect(mockFetch).not.toHaveBeenCalled();
});

const pageBody = (kind: string, ids: string[], next: string | null) => ({
  snapshot: { snapshot_id: snapshot, revision: "rev", coverage: { state: "open", missing_keys: [] }, counts: { node: 3, gap: 1 } },
  kind, filters: {}, item_keys: [], body_overrides: [], next_cursor: next,
  items: kind === "gap" ? ids.map(reason => ({ reason, node_keys: [], evidence_ids: [] }))
    : ids.map(local_id => ({ ref: { kind: "platform", source_instance_id: "s", local_id }, evidence: [] })),
});
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

it("forwards phase and attempt filters on page reads", async () => {
  mockFetch.mockResolvedValue(json(pageBody("node", [], null)));
  await synGetSessionInventory(client, { execution_id: "run", snapshot_id: snapshot, phase_id: "phase one", attempt_id: "a-1" });
  const url = new URL(mockFetch.mock.calls[0]![0] as string);
  expect(url.searchParams.get("phase_id")).toBe("phase one");
  expect(url.searchParams.get("attempt_id")).toBe("a-1");
});

it.each([
  [{ phase_id: " " }, "phase_id"],
  [{ attempt_id: "x".repeat(2049) }, "attempt_id"],
  [{ node_key: "not-hex" }, "node_key"],
])("rejects invalid selectors %j before network access", async (extra, message) => {
  const result = await synGetSessionInventory(client, { execution_id: "run", snapshot_id: snapshot, ...extra });
  expect(result.isError).toBe(true);
  expect(result.content).toContain(message);
  expect(mockFetch).not.toHaveBeenCalled();
});

it("requires a snapshot for filters instead of guessing the head", async () => {
  const result = await synGetSessionInventory(client, { execution_id: "run", phase_id: "p" });
  expect(result.isError).toBe(true);
  expect(mockFetch).not.toHaveBeenCalled();
});

it("resolves a cross-page node key within the pinned snapshot", async () => {
  const key = "c".repeat(64);
  mockFetch.mockResolvedValue(json({ snapshot_id: snapshot, node_key: key, status: "unresolved", node: null }));
  const result = await synGetSessionInventory(client, { execution_id: "run", snapshot_id: snapshot, node_key: key });
  expect(JSON.parse(result.content).status).toBe("unresolved");
  expect(mockFetch.mock.calls[0]![0]).toBe(`https://deployment.example/api/v1/executions/run/session-inventory/${snapshot}/nodes/${key}`);
});

it("all mode reads every page of every section from one revision and keeps gaps", async () => {
  const status = { snapshot: { snapshot_id: snapshot, revision: "rev" }, reconstruction_status: "current", later_evidence_pending: false, summary: { complete: false } };
  mockFetch.mockImplementation(async (input: string) => {
    const url = new URL(input);
    if (url.pathname.endsWith("/session-inventory")) return json(status);
    const kind = url.pathname.split("/").pop()!;
    if (kind === "node") return json(url.searchParams.get("cursor") === "c1" ? pageBody("node", ["two"], null) : pageBody("node", ["one"], "c1"));
    if (kind === "gap") return json(pageBody("gap", ["capture_pending"], null));
    return json(pageBody(kind, [], null));
  });
  const result = JSON.parse((await synGetSessionInventory(client, { execution_id: "run", all: true })).content);
  expect(result.sections.node.items.map((n: { ref: { local_id: string } }) => n.ref.local_id)).toEqual(["one", "two"]);
  expect(result.sections.node.truncated).toBe(false);
  expect(result.gaps).toEqual([{ reason: "capture_pending", node_keys: [], evidence_ids: [] }]);
  expect(result.summary).toEqual({ complete: false });
  expect(Object.keys(result.sections).sort()).toEqual(["binding", "capture", "edge", "gap", "membership", "node", "retraction"]);
  const pageUrls = mockFetch.mock.calls.slice(1).map(c => new URL(c[0] as string));
  expect(pageUrls.every(u => u.pathname.includes(snapshot))).toBe(true);
});

it("all mode rejects a response from another revision", async () => {
  mockFetch.mockResolvedValueOnce(json({ snapshot: { snapshot_id: snapshot }, summary: {} }))
    .mockResolvedValueOnce(json({ ...pageBody("node", [], null), snapshot: { snapshot_id: "22222222-2222-4222-8222-222222222222" } }));
  const result = await synGetSessionInventory(client, { execution_id: "run", all: true, kind: "node" });
  expect(result.isError).toBe(true);
  expect(result.content).toContain("another revision");
});

it("all mode without a published revision reports none rather than an empty inventory", async () => {
  mockFetch.mockResolvedValueOnce(json({ snapshot: null, reconstruction_status: "pending", later_evidence_pending: false, summary: { complete: false } }));
  const result = JSON.parse((await synGetSessionInventory(client, { execution_id: "run", all: true })).content);
  expect(result.snapshot_id).toBeNull();
  expect(result.gaps).toBeNull();
  expect(mockFetch).toHaveBeenCalledTimes(1);
});

it("surfaces structured cursor errors with their restart instructions", async () => {
  mockFetch.mockResolvedValue(json({ detail: { code: "cursor_expired", message: "gone", mismatched: [], restart: true, restart_snapshot_id: snapshot } }, 410));
  const result = await synGetSessionInventory(client, { execution_id: "run", snapshot_id: snapshot, cursor: "old" });
  expect(result.isError).toBe(true);
  expect(result.content).toContain("410");
  expect(result.content).toContain("cursor_expired");
  expect(result.content).toContain(snapshot);
});

describe("all-mode completeness", () => {
  const reconciled = { snapshot: { snapshot_id: snapshot, revision: "rev" }, reconstruction_status: "current", later_evidence_pending: false, summary: { complete: true } };
  function serveTwoNodePages() {
    mockFetch.mockImplementation(async (input: string) => {
      const url = new URL(input);
      if (url.pathname.endsWith("/session-inventory")) return json(reconciled);
      const kind = url.pathname.split("/").pop()!;
      if (kind === "node") return json(url.searchParams.get("cursor") === "c1" ? pageBody("node", ["two"], null) : pageBody("node", ["one"], "c1"));
      return json(pageBody(kind, [], null));
    });
  }

  it("reconciled coverage with an exhausted page budget is not complete", async () => {
    serveTwoNodePages();
    const result = JSON.parse((await synGetSessionInventory(client, { execution_id: "run", all: true }, { maxPages: 1 })).content);
    expect(result.coverage_complete).toBe(true);
    expect(result.traversal_complete).toBe(false);
    expect(result.complete).toBe(false);
    expect(result.pending_sections).toEqual(["node", "membership", "edge", "capture", "gap", "retraction", "binding"]);
    expect(result.note).toContain("provisional");
    expect(result.gaps).toBeNull();
  });

  it("reconciled coverage with a full unfiltered traversal is complete", async () => {
    serveTwoNodePages();
    const result = JSON.parse((await synGetSessionInventory(client, { execution_id: "run", all: true })).content);
    expect(result).toMatchObject({ coverage_complete: true, traversal_complete: true, complete: true, pending_sections: [] });
    expect(result.note).toBeUndefined();
  });

  it("a single-section or filtered traversal never claims completeness", async () => {
    serveTwoNodePages();
    const one = JSON.parse((await synGetSessionInventory(client, { execution_id: "run", all: true, kind: "node" })).content);
    expect(one).toMatchObject({ traversal_complete: false, complete: false });
    expect(one.pending_sections).not.toContain("node");
    const filtered = JSON.parse((await synGetSessionInventory(client, { execution_id: "run", all: true, phase_id: "p" })).content);
    expect(filtered).toMatchObject({ traversal_complete: false, complete: false, pending_sections: [] });
    expect(filtered.note).toContain("subset");
  });

  it("single-page reads carry no top-level completeness claim", async () => {
    serveTwoNodePages();
    const page = JSON.parse((await synGetSessionInventory(client, { execution_id: "run", snapshot_id: snapshot })).content);
    expect(page.complete).toBeUndefined();
    expect(page.traversal_complete).toBeUndefined();
  });
});
