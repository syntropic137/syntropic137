import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { metricsGroup } from "../../src/commands/metrics.js";

describe("metrics commands", () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
    vi.spyOn(process.stdout, "write").mockReturnValue(true);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  function jsonResponse(data: unknown, status = 200): Response {
    return new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  function stdout(): string {
    return (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls
      .map((c: unknown[]) => String(c[0]))
      .join("");
  }

  describe("show", () => {
    const handler = metricsGroup.getCommand("show")!.handler;

    it("renders aggregated metrics", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          total_workflows: 5,
          total_sessions: 12,
          total_input_tokens: 50000,
          total_output_tokens: 25000,
          total_cost_usd: "1.50",
          total_artifacts: 8,
          phases: [
            {
              phase_name: "planning",
              status: "completed",
              total_tokens: 10000,
              cost_usd: "0.30",
              duration_seconds: 120,
              artifact_count: 2,
            },
          ],
        }),
      );

      await handler({ positionals: [], values: {} });
      const out = stdout();
      expect(out).toContain("5");
      expect(out).toContain("12");
      expect(out).toContain("planning");
    });

    it("shows no-data message when empty", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          total_workflows: 0,
          total_sessions: 0,
          total_input_tokens: 0,
          total_output_tokens: 0,
          total_cost_usd: "0.00",
          total_artifacts: 0,
          phases: [],
        }),
      );

      await handler({ positionals: [], values: {} });
      expect(stdout()).toContain("No metrics data available");
    });

    it("renders metrics with phases table", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          total_workflows: 3,
          total_sessions: 6,
          total_input_tokens: 30000,
          total_output_tokens: 15000,
          total_cost_usd: "0.90",
          total_artifacts: 4,
          phases: [
            {
              phase_name: "research",
              status: "completed",
              total_tokens: 20000,
              cost_usd: "0.50",
              duration_seconds: 60,
              artifact_count: 1,
            },
            {
              phase_name: "implementation",
              status: "running",
              total_tokens: 10000,
              cost_usd: "0.40",
              duration_seconds: 300,
              artifact_count: 3,
            },
          ],
        }),
      );

      await handler({ positionals: [], values: {} });
      const out = stdout();
      expect(out).toContain("research");
      expect(out).toContain("implementation");
    });
  });
});
