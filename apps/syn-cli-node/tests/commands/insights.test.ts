import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { insightsGroup } from "../../src/commands/insights.js";
import type { components } from "../../src/generated/api-types.js";

type GlobalCostResponse = components["schemas"]["GlobalCostResponse"];

function globalCost(overrides: Partial<GlobalCostResponse> = {}): GlobalCostResponse {
  return {
    system_id: "",
    system_name: "All Systems",
    organization_id: "",
    total_cost_usd: "1.50",
    total_cost_display: "$1.50",
    unpriced_observation_count: 0,
    total_tokens: 100000,
    total_input_tokens: 60000,
    total_output_tokens: 40000,
    total_cache_creation_tokens: 0,
    total_cache_read_tokens: 0,
    cost_by_repo: {},
    cost_by_workflow: {},
    unpriced_by_workflow: {},
    cost_by_model: {},
    execution_count: 1,
    ...overrides,
  };
}

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
      jsonResponse(globalCost({ cost_by_repo: { "test-repo": "1.50" } })),
    );

    await insightsGroup.getCommand("cost")!.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toContain("$1.50");
    expect(out).toContain("test-repo");
  });

  it("cost renders the unattributed model bucket as unknown", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse(
        globalCost({
          cost_by_model: { "claude-opus-5-5": "1.00", "unattributed-model": "0.50" },
        }),
      ),
    );

    await insightsGroup.getCommand("cost")!.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toContain("claude-opus-5-5");
    expect(out).toContain("unknown");
    expect(out).not.toContain("unattributed-model");
  });

  // #897: the API decides how honest the total is (total_cost_display); the
  // CLI prints that verdict instead of formatting total_cost_usd itself.
  it("cost prints a partial total as partial and names the unpriced count", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse(
        globalCost({
          total_cost_usd: "1.25",
          total_cost_display: ">=$1.25 (partial)",
          unpriced_observation_count: 9,
          unpriced_by_workflow: { "wf-1": 9 },
        }),
      ),
    );

    await insightsGroup.getCommand("cost")!.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toContain(">=$1.25 (partial)");
    expect(out).toContain("9 observation(s) had no rate");
    expect(out).not.toMatch(/Total cost:\S*\s+\$1\.25/);
  });

  it("cost prints an unpriced total as unpriced and names the unpriced count", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse(
        globalCost({
          total_cost_usd: "0",
          total_cost_display: "unpriced",
          unpriced_observation_count: 4,
          unpriced_by_workflow: { "wf-1": 4 },
        }),
      ),
    );

    await insightsGroup.getCommand("cost")!.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toMatch(/Total cost:\S*\s+unpriced/);
    expect(out).toContain("4 observation(s) had no rate");
    expect(out).not.toContain("$0.00");
  });

  it("cost prints a fully priced total with no unpriced line", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse(globalCost({ total_cost_usd: "1.25", total_cost_display: "$1.25" })),
    );

    await insightsGroup.getCommand("cost")!.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toMatch(/Total cost:\S*\s+\$1\.25/);
    expect(out).not.toContain("had no rate");
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
