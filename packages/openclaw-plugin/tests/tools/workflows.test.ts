import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SyntropicClient } from "../../src/client.js";
import { synExecuteWorkflow, synListWorkflows } from "../../src/tools/workflows.js";
import { executeResponse, workflowList } from "../fixtures/responses.js";

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

describe("synListWorkflows", () => {
  it("returns formatted workflow list", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(workflowList));

    const result = await synListWorkflows(client, {});

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("Issue Resolution");
    expect(result.content).toContain("wf-issue-001");
    expect(result.content).toContain("2 total");
    expect(result.content).toContain("3 phase(s)");
  });

  it("passes filter params", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(workflowList));

    await synListWorkflows(client, { workflow_type: "issue", page: 2 });

    const [url] = mockFetch.mock.calls[0]!;
    const parsed = new URL(url as string);
    expect(parsed.searchParams.get("workflow_type")).toBe("issue");
    expect(parsed.searchParams.get("page")).toBe("2");
  });

  it("handles empty list", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ workflows: [], total: 0, page: 1, page_size: 20 }),
    );

    const result = await synListWorkflows(client, {});
    expect(result.content).toBe("No workflows found.");
  });

  it("returns error on API failure", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response("Internal Server Error", { status: 500, statusText: "ISE" }),
    );

    const result = await synListWorkflows(client, {});
    expect(result.isError).toBe(true);
    expect(result.content).toContain("500");
  });
});

describe("synExecuteWorkflow", () => {
  it("returns execution started info", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(executeResponse));

    const result = await synExecuteWorkflow(client, {
      workflow_id: "wf-issue-001",
      inputs: { issue_url: "https://github.com/org/repo/issues/42" },
    });

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("exec-abc-123");
    expect(result.content).toContain("syn_get_execution");
  });

  it("sends correct POST body", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(executeResponse));

    await synExecuteWorkflow(client, {
      workflow_id: "wf-issue-001",
      inputs: { issue_url: "https://example.com" },
      provider: "claude",
      max_budget_usd: 5.0,
    });

    const [, init] = mockFetch.mock.calls[0]!;
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.inputs).toEqual({ issue_url: "https://example.com" });
    expect(body.provider).toBe("claude");
    expect(body.max_budget_usd).toBe(5.0);
  });
});
