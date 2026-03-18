import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SyntropicClient } from "../../src/client.js";
import { synGetExecution, synListExecutions } from "../../src/tools/executions.js";
import { executionDetail, executionList } from "../fixtures/responses.js";

const mockFetch = vi.fn<typeof globalThis.fetch>();
let client: SyntropicClient;

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  client = new SyntropicClient({ apiUrl: "http://localhost:8137" });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonResponse(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("synListExecutions", () => {
  it("returns formatted execution list", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(executionList));

    const result = await synListExecutions(client, {});

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("Issue Resolution");
    expect(result.content).toContain("running");
    expect(result.content).toContain("1/3 phases");
  });

  it("handles empty list", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ executions: [], total: 0, page: 1, page_size: 50 }),
    );

    const result = await synListExecutions(client, {});
    expect(result.content).toBe("No executions found.");
  });
});

describe("synGetExecution", () => {
  it("returns detailed execution info", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(executionDetail));

    const result = await synGetExecution(client, { execution_id: "exec-abc-123" });

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("Issue Resolution");
    expect(result.content).toContain("completed");
    expect(result.content).toContain("$0.75");
    expect(result.content).toContain("Analyze");
    expect(result.content).toContain("Implement");
    expect(result.content).toContain("art-001");
  });

  it("handles 404", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Not found" }), { status: 404 }),
    );

    const result = await synGetExecution(client, { execution_id: "nonexistent" });
    expect(result.isError).toBe(true);
    expect(result.content).toContain("404");
  });
});
