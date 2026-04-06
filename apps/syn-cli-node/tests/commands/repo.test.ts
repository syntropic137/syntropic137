import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { repoGroup } from "../../src/commands/repo.js";
import { CLIError } from "../../src/framework/errors.js";

describe("repo commands", () => {
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
        health_status: "healthy",
        success_rate: 0.95,
        avg_duration_ms: 45000,
        total_executions: 20,
        trends: [],
      }),
    );
    await repoGroup.getCommand("health")!.handler({ positionals: ["repo-1"], values: {} });
    const out = stdout();
    expect(out).toContain("healthy");
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

    it("errors when no organizations exist", async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({ organizations: [], total: 0 }),
      );

      await expect(
        repoGroup.getCommand("register")!.handler({
          positionals: [],
          values: { url: "owner/repo" },
        }),
      ).rejects.toThrow(CLIError);
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
});
