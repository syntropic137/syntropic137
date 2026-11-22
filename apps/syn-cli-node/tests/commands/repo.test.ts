import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { repoGroup } from "../../src/commands/repo.js";
import { CLIError } from "../../src/framework/errors.js";
import type { components } from "../../src/generated/api-types.js";

type RepoCostResponse = components["schemas"]["RepoCostResponse"];

function repoCost(overrides: Partial<RepoCostResponse> = {}): RepoCostResponse {
  return {
    repo_id: "repo-1",
    repo_full_name: "acme/api",
    total_cost_usd: "1.50",
    total_cost_display: "$1.50",
    unpriced_observation_count: 0,
    total_tokens: 100000,
    total_input_tokens: 60000,
    total_output_tokens: 40000,
    cost_by_workflow: {},
    cost_by_model: {},
    execution_count: 1,
    ...overrides,
  };
}

describe("repo commands", () => {
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

  it("register requires --url", async () => {
    await expect(
      repoGroup.getCommand("register")!.handler({ positionals: [], values: {} }),
    ).rejects.toThrow(CLIError);
  });

  it("register succeeds", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ repo_id: "repo-1", full_name: "owner/repo" }));
    await repoGroup.getCommand("register")!.handler({ positionals: [], values: { url: "owner/repo", org: "org-1" } });
    expect(stdout()).toContain("Repository registered");
  });

  it("list shows repos", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({ repos: [{ repo_id: "repo-1", full_name: "owner/repo", system_id: "" }], total: 1 }),
    );
    await repoGroup.getCommand("list")!.handler({ positionals: [], values: {} });
    expect(stdout()).toContain("owner/repo");
  });

  it("health shows health metrics", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        repo_id: "repo-1",
        repo_full_name: "owner/repo",
        success_rate: 0.95,
        trend: "stable",
        total_executions: 20,
        recent_cost_usd: "1.50",
        window_tokens: 5000,
        last_execution_at: "2026-01-01T00:00:00Z",
      }),
    );
    await repoGroup.getCommand("health")!.handler({ positionals: ["repo-1"], values: {} });
    const out = stdout();
    expect(out).toContain("stable");
    expect(out).toContain("95.0%");
  });

  it("assign requires --system", async () => {
    await expect(
      repoGroup.getCommand("assign")!.handler({ positionals: ["repo-1"], values: {} }),
    ).rejects.toThrow(CLIError);
  });

  it("failures shows empty message", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ failures: [], total: 0 }));
    await repoGroup.getCommand("failures")!.handler({ positionals: ["repo-1"], values: {} });
    expect(stdout()).toContain("No recent failures");
  });

  describe("register org auto-selection", () => {
    it("auto-selects the only organization", async () => {
      // First call: list orgs (returns one org)
      // Second call: register repo
      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({ organizations: [{ organization_id: "org-42" }], total: 1 }),
        )
        .mockResolvedValueOnce(
          jsonResponse({ repo_id: "repo-1", full_name: "owner/repo" }),
        );

      await repoGroup.getCommand("register")!.handler({
        positionals: [],
        values: { url: "owner/repo" },
      });
      const out = stdout();
      expect(out).toContain("Using organization: org-42");
      expect(out).toContain("Repository registered");
    });

    it("registers without org when no organizations exist", async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({ organizations: [], total: 0 }),
      );
      mockFetch.mockResolvedValueOnce(
        jsonResponse({ repo_id: "repo-99", full_name: "owner/repo" }),
      );

      await repoGroup.getCommand("register")!.handler({
        positionals: [],
        values: { url: "owner/repo" },
      });
      const out = stdout();
      expect(out).toContain("Repository registered: repo-99");
      // Should NOT contain org selection message
      expect(out).not.toContain("Using organization:");
    });

    it("errors when multiple organizations exist without --org", async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          organizations: [
            { organization_id: "org-1" },
            { organization_id: "org-2" },
          ],
          total: 2,
        }),
      );

      await expect(
        repoGroup.getCommand("register")!.handler({
          positionals: [],
          values: { url: "owner/repo" },
        }),
      ).rejects.toThrow(CLIError);
    });

    it("errors when org ID is missing from API response", async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({ organizations: [{ name: "My Org" }], total: 1 }),
      );

      await expect(
        repoGroup.getCommand("register")!.handler({
          positionals: [],
          values: { url: "owner/repo" },
        }),
      ).rejects.toThrow(CLIError);
    });

    it("errors when org ID is empty string", async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({ organizations: [{ organization_id: "" }], total: 1 }),
      );

      await expect(
        repoGroup.getCommand("register")!.handler({
          positionals: [],
          values: { url: "owner/repo" },
        }),
      ).rejects.toThrow(CLIError);
    });
  });

  // #897: the API decides how honest the total is (total_cost_display); the
  // CLI prints that verdict instead of formatting total_cost_usd itself.
  describe("cost", () => {
    async function runCost(data: RepoCostResponse): Promise<string> {
      mockFetch.mockResolvedValue(jsonResponse(data));
      await repoGroup.getCommand("cost")!.handler({ positionals: ["repo-1"], values: {} });
      return stdout();
    }

    it("prints a partial total as partial and names the unpriced count", async () => {
      const out = await runCost(
        repoCost({ total_cost_usd: "1.25", total_cost_display: ">=$1.25 (partial)", unpriced_observation_count: 9 }),
      );
      expect(out).toContain(">=$1.25 (partial)");
      expect(out).toContain("9 observation(s) had no rate");
      expect(out).not.toMatch(/Total cost:\s+\$1\.25/);
    });

    it("prints an unpriced total as unpriced and names the unpriced count", async () => {
      const out = await runCost(
        repoCost({ total_cost_usd: "0", total_cost_display: "unpriced", unpriced_observation_count: 4 }),
      );
      expect(out).toMatch(/Total cost:\s+unpriced/);
      expect(out).toContain("4 observation(s) had no rate");
      expect(out).not.toContain("$0.00");
    });

    it("prints a fully priced total with no unpriced line", async () => {
      const out = await runCost(repoCost({ total_cost_usd: "1.25", total_cost_display: "$1.25" }));
      expect(out).toMatch(/Total cost:\s+\$1\.25/);
      expect(out).not.toContain("had no rate");
    });
  });
});
