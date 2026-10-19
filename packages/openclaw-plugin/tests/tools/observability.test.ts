import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SyntropicClient } from "../../src/client.js";
import {
  synGetExecutionCost,
  synGetMetrics,
  synGetSession,
} from "../../src/tools/observability.js";
import type { PhaseMetrics } from "../../src/types.js";
import { executionCost, metricsResponse, sessionDetail } from "../fixtures/responses.js";

const mockFetch = vi.fn<typeof globalThis.fetch>();
let client: SyntropicClient;

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  client = new SyntropicClient({ apiUrl: "http://localhost:8137" });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.resetAllMocks();
});

function jsonResponse(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("synGetSession", () => {
  it("returns formatted session detail", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(sessionDetail));

    const result = await synGetSession(client, { session_id: "sess-001" });

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("sess-001");
    expect(result.content).toContain("claude");
    expect(result.content).toContain("completed");
    expect(result.content).toContain("Read");
    expect(result.content).toContain("abc1234");
  });

  it("handles 404", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Not found" }), { status: 404 }),
    );

    const result = await synGetSession(client, { session_id: "nonexistent" });
    expect(result.isError).toBe(true);
  });
});

describe("synGetExecutionCost", () => {
  it("returns formatted cost breakdown", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(executionCost));

    const result = await synGetExecutionCost(client, { execution_id: "exec-abc-123" });

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("$0.75");
    expect(result.content).toContain("phase-analyze");
    expect(result.content).toContain("claude-sonnet-4-6");
    expect(result.content).toContain("Cost by Tool");
  });

  it("renders a cost the API reports without breakdowns (#1182)", async () => {
    // cost_by_* are optional in the schema; Object.entries(undefined) threw.
    const { cost_by_phase: _p, cost_by_model: _m, cost_by_tool: _t, ...rest } = executionCost;
    mockFetch.mockResolvedValueOnce(jsonResponse(rest));

    const result = await synGetExecutionCost(client, { execution_id: "exec-abc-123" });

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("$0.75");
    expect(result.content).not.toContain("Cost by");
  });

  it("passes query params", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(executionCost));

    await synGetExecutionCost(client, { execution_id: "e1" });

    const [url] = mockFetch.mock.calls[0]!;
    const parsed = new URL(url as string);
    expect(parsed.searchParams.get("include_breakdown")).toBe("true");
    expect(parsed.searchParams.get("include_session_ids")).toBe("true");
  });
});

describe("synGetMetrics", () => {
  it("returns formatted platform metrics", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(metricsResponse));

    const result = await synGetMetrics(client, {});

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("Platform Metrics");
    expect(result.content).toContain("5");
    expect(result.content).toContain("$5.25");
  });

  it("renders a phase the API reports with no duration (#1182)", async () => {
    const phase: PhaseMetrics = {
      phase_id: "phase-run", phase_name: "Run", status: "running", input_tokens: 10, output_tokens: 5,
      total_tokens: 15, cost_usd: "0.01", unpriced_observation_count: 0, cost_in_progress: true,
      duration_seconds: null, artifact_count: 0,
    };
    mockFetch.mockResolvedValueOnce(jsonResponse({ ...metricsResponse, phases: [phase] }));

    const result = await synGetMetrics(client, {});

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("**Run** (running) — 15 tokens, $0.01, n/a");
  });

  it("passes workflow_id filter", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(metricsResponse));

    await synGetMetrics(client, { workflow_id: "wf-001" });

    const [url] = mockFetch.mock.calls[0]!;
    const parsed = new URL(url as string);
    expect(parsed.searchParams.get("workflow_id")).toBe("wf-001");
  });
});
