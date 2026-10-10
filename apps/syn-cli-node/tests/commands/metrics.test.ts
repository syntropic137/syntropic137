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
    vi.resetAllMocks();
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

  describe("profiles", () => {
    const handler = metricsGroup.getCommand("profiles")!.handler;

    const pct = (n: number) => ({ n, p50: null, p95: null, p50_display: "insufficient", p95_display: "insufficient" });

    it("prints every coverage count and each measure's sample size", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          workflow_id: "wf-1",
          since: "2026-10-01T00:00:00Z",
          until: "2026-10-08T00:00:00Z",
          window_days: 7,
          executions: 40,
          tokens: [],
          resources: [
            {
              phase_id: "plan",
              cpu_seconds_per_wall_second: pct(23),
              cpu_throttled_seconds: pct(29),
              memory_peak_bytes: pct(31),
              disk_bytes_at_teardown: pct(37),
              coverage: {
                phases: 41,
                phases_without_usage_row: 2,
                cpu_usage_seconds_missing: 3,
                cpu_throttled_seconds_missing: 5,
                memory_peak_bytes_missing: 7,
                disk_bytes_at_teardown_missing: 11,
                wall_seconds_missing: 13,
                coverage_display: "39/41 phases measured",
              },
            },
          ],
        }),
      );

      await handler({ positionals: [], values: { workflow: "wf-1" } });
      const row = stdout().split("\n").filter((l) => l.includes("plan")).at(-1) ?? "";
      for (const cell of ["41", "2", "23 / 3", "13", "29 / 5", "31 / 7", "37 / 11"]) {
        expect(row).toContain(cell);
      }
    });
  });

  describe("shipped", () => {
    const handler = metricsGroup.getCommand("shipped")!.handler;
    const count = (total: number | null, delta: string | null, reason: string | null = null) => ({
      total, previous_total: null, delta: null, delta_percent: null,
      delta_display: delta, delta_unit: "percent", total_display: total === null ? null : total.toLocaleString("en-US"),
      series: [], source: "s", reason,
    });
    const body = {
      window: { days: 14, from: "2026-09-26", to: "2026-10-09" },
      previous: { from: "2026-09-12", to: "2026-09-25" },
      workflow_id: null,
      commits: count(1204, "+38%"),
      prs_opened: count(null, null, "PR outcomes are not persisted"),
      prs_merged: count(null, null, "PR outcomes are not persisted"),
      merge_rate: { ...count(null, null, "PR outcomes are not persisted"), delta_unit: "points" },
      repos_touched: { ...count(9, "+3"), delta_unit: "count" },
      repos: ["acme/api"],
      by_workflow: [{ workflow_id: "wf", name: "Implement", commits: 1204, prs_opened: 73, prs_merged: 61, repos_touched: 9 }],
      unavailable: ["prs_opened", "prs_merged", "merge_rate"],
    };

    it("asks for the window and renders tiles, reasons and workflows", async () => {
      mockFetch.mockResolvedValue(jsonResponse(body));
      await handler({ positionals: [], values: { days: "14" } });
      const url = String((mockFetch.mock.calls[0]![0] as Request).url ?? mockFetch.mock.calls[0]![0]);
      expect(url).toContain("/metrics/shipped");
      expect(url).toContain("days=14");
      const out = stdout();
      expect(out).toContain("1,204");
      expect(out).toContain("+38%");
      expect(out).toContain("+3");
      expect(out).toContain("PR outcomes are not persisted");
      expect(out).toContain("Implement");
    });

    it("prints raw JSON with --json", async () => {
      mockFetch.mockResolvedValue(jsonResponse(body));
      await handler({ positionals: [], values: { days: "14", json: true } });
      expect(JSON.parse(stdout())).toEqual(body);
    });

    it("refuses a window the API does not offer", async () => {
      await handler({ positionals: [], values: { days: "10" } });
      expect(mockFetch).not.toHaveBeenCalled();
      expect(process.exitCode).toBe(1);
      process.exitCode = 0;
    });
  });
});
