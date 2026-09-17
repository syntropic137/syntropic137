import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SyntropicClient } from "../../src/client.js";
import { synCreateTrigger, synListTriggers } from "../../src/tools/triggers.js";
import { triggerCreated, triggerList } from "../fixtures/responses.js";

const mockFetch = vi.fn<typeof globalThis.fetch>();
let client: SyntropicClient;

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  client = new SyntropicClient({ apiUrl: "http://localhost:8137" });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

function jsonResponse(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("synListTriggers", () => {
  it("returns formatted trigger list", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(triggerList));

    const result = await synListTriggers(client, {});

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("Auto-resolve issues");
    expect(result.content).toContain("issues.opened");
    expect(result.content).toContain("org/repo");
    expect(result.content).toContain("7×");
  });

  it("handles empty list", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ triggers: [], total: 0 }));

    const result = await synListTriggers(client, {});
    expect(result.content).toBe("No trigger rules found.");
  });

  it("passes filter params", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(triggerList));

    await synListTriggers(client, { repository: "org/repo", status: "active" });

    const [url] = mockFetch.mock.calls[0]!;
    const parsed = new URL(url as string);
    expect(parsed.searchParams.get("repository")).toBe("org/repo");
    expect(parsed.searchParams.get("status")).toBe("active");
  });
});

describe("synCreateTrigger", () => {
  it("names the deployment the trigger will fire workflows on (issue #1264)", async () => {
    // A trigger holds a host-relative workflow ID and fires it LATER, so the
    // ambiguity outlives this call: the result has to pin the workflow ID to
    // the deployment it was created against. The environment points elsewhere
    // so a result built from anything but the client is visible.
    vi.stubEnv("SYNTROPIC_URL", "http://100.114.86.77:8137");
    const vps = new SyntropicClient({ apiUrl: "http://100.112.178.5:8137" });
    mockFetch.mockResolvedValueOnce(jsonResponse(triggerCreated));

    const result = await synCreateTrigger(vps, {
      name: "PR Review Trigger",
      event: "pull_request.opened",
      repository: "org/repo",
      workflow_id: "wf-review-001",
    });

    const [url, init] = mockFetch.mock.calls[0]!;
    const createdOn = new URL(url as string).origin;
    expect(createdOn).toBe("http://100.112.178.5:8137");
    const posted = JSON.parse((init as RequestInit).body as string) as { workflow_id: string };
    expect(posted.workflow_id).toBe("wf-review-001");

    expect(result.content).toContain(createdOn);
    expect(result.content).toContain(posted.workflow_id);
    expect(result.content).toContain("trig-002");
    expect(result.content).not.toContain("100.114.86.77");
  });

  it("returns created trigger info", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(triggerCreated));

    const result = await synCreateTrigger(client, {
      name: "PR Review Trigger",
      event: "pull_request.opened",
      repository: "org/repo",
      workflow_id: "wf-review-001",
    });

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("Trigger Created");
    expect(result.content).toContain("trig-002");
    expect(result.content).toContain("active");
  });

  it("sends full body with optional fields", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(triggerCreated));

    await synCreateTrigger(client, {
      name: "Test",
      event: "issues.opened",
      repository: "org/repo",
      workflow_id: "wf-001",
      conditions: { labels: ["bug"] },
      input_mapping: { issue_url: "{{issue.html_url}}" },
    });

    const [, init] = mockFetch.mock.calls[0]!;
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.name).toBe("Test");
    expect(body.conditions).toEqual({ labels: ["bug"] });
    expect(body.input_mapping).toEqual({ issue_url: "{{issue.html_url}}" });
  });
});
