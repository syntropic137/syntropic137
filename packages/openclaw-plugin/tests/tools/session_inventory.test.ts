import { afterEach, beforeEach, expect, it, vi } from "vitest";
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
