import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { systemGroup } from "../../src/commands/system.js";
import { CLIError } from "../../src/framework/errors.js";

describe("system commands", () => {
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

  it("create requires --name", async () => {
    await expect(
      systemGroup.getCommand("create")!.handler({ positionals: [], values: {} }),
    ).rejects.toThrow(CLIError);
  });

  it("create succeeds", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ system_id: "sys-1", name: "Backend" }));
    await systemGroup.getCommand("create")!.handler({ positionals: [], values: { name: "Backend" } });
    expect(stdout()).toContain("System created");
  });

  it("list shows systems", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({ systems: [{ system_id: "sys-1", name: "Backend", repo_count: 3, organization_id: "org-1" }], total: 1 }),
    );
    await systemGroup.getCommand("list")!.handler({ positionals: [], values: {} });
    expect(stdout()).toContain("Backend");
  });

  it("status shows health", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        name: "Backend",
        health_status: "healthy",
        repo_count: 3,
        active_executions: 1,
        repos: [],
      }),
    );
    await systemGroup.getCommand("status")!.handler({ positionals: ["sys-1"], values: {} });
    const out = stdout();
    expect(out).toContain("Backend");
    expect(out).toContain("healthy");
  });

  it("delete requires --force", async () => {
    await expect(
      systemGroup.getCommand("delete")!.handler({ positionals: ["sys-1"], values: {} }),
    ).rejects.toThrow(CLIError);
  });

  it("patterns shows failure patterns", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        failure_patterns: [{ pattern: "timeout in phase-2", count: 5 }],
        cost_outliers: [],
      }),
    );
    await systemGroup.getCommand("patterns")!.handler({ positionals: ["sys-1"], values: {} });
    expect(stdout()).toContain("timeout in phase-2");
  });
});
