import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { insightsGroup } from "../../src/commands/insights.js";

describe("insights commands", () => {
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

  it("overview shows system summary", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        total_systems: 3,
        total_repos: 10,
        active_sessions: 2,
        total_executions: 50,
        health: { status: "healthy" },
        systems: [],
      }),
    );

    await insightsGroup.getCommand("overview")!.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toContain("System Overview");
    expect(out).toContain("3");
    expect(out).toContain("10");
  });

  it("cost shows cost breakdown", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        total_cost_usd: "1.50",
        total_tokens: 100000,
        cost_by_repo: { "test-repo": "1.50" },
        cost_by_model: {},
      }),
    );

    await insightsGroup.getCommand("cost")!.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toContain("$1.50");
    expect(out).toContain("test-repo");
  });

  it("cost renders the unattributed model bucket as unknown", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        total_cost_usd: "1.50",
        total_tokens: 100000,
        cost_by_repo: {},
        cost_by_model: { "claude-opus-5-5": "1.00", "unattributed-model": "0.50" },
      }),
    );

    await insightsGroup.getCommand("cost")!.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toContain("claude-opus-5-5");
    expect(out).toContain("unknown");
    expect(out).not.toContain("unattributed-model");
  });

  it("heatmap renders sparkline", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        metric: "sessions",
        start_date: "2026-03-20",
        end_date: "2026-04-03",
        total: 18,
        days: [
          { date: "2026-03-20", count: 5 },
          { date: "2026-03-21", count: 10 },
          { date: "2026-03-22", count: 3 },
          { date: "2026-03-23", count: 0 },
        ],
      }),
    );

    await insightsGroup.getCommand("heatmap")!.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toContain("Activity Heatmap");
    expect(out).toContain("18 total events");
  });
  it("latency prints the recorder's drop counters even when no rows were recorded", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        window: "24h",
        since: "2026-10-07T00:00:00+00:00",
        available: true,
        routes: [],
        recorder: { running: false, written: 0, dropped: 42, write_failures: 3, discarded: 5, cleanup_failures: 2, buffered: 0 },
      }),
    );

    await insightsGroup.getCommand("latency")!.handler({ positionals: [], values: { window: "24h" } });
    const out = stdout();
    expect(out).toContain("NOT running");
    expect(out).toContain("42 dropped");
    expect(out).toContain("3 failed writes");
    expect(out).toContain("5 discarded");
    expect(out).toContain("2 connection cleanups failed");
  });

  it("latency prints one row per route", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        window: "7d",
        since: "2026-10-01T00:00:00+00:00",
        available: true,
        routes: [
          { method: "GET", route: "/evals", count: 12, p50_ms: 40, p95_ms: 900, p99_ms: 24500, max_ms: 26000, p99_display: "24.5 s" },
        ],
        recorder: { running: true, written: 12, dropped: 0, write_failures: 0, discarded: 0, cleanup_failures: 0, buffered: 0 },
      }),
    );

    await insightsGroup.getCommand("latency")!.handler({ positionals: [], values: { window: "7d" } });
    const out = stdout();
    expect(out).toContain("/evals");
    expect(out).toContain("24500");
    expect(out).toContain("arrival to response start");
    expect(out).not.toContain("dropped");
  });
});
