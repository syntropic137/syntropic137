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
});
