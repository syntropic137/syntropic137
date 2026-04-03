import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { orgGroup } from "../../src/commands/org.js";
import { CLIError } from "../../src/framework/errors.js";

describe("org commands", () => {
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
    const handler = orgGroup.getCommand("create")!.handler;
    await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
  });

  it("create succeeds with --name", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ organization_id: "org-1", name: "TestOrg" }));
    const handler = orgGroup.getCommand("create")!.handler;
    await handler({ positionals: [], values: { name: "TestOrg" } });
    expect(stdout()).toContain("Organization created");
  });

  it("list shows organizations", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({ organizations: [{ organization_id: "org-1", name: "Acme", slug: "acme", system_count: 2, repo_count: 5 }], total: 1 }),
    );
    const handler = orgGroup.getCommand("list")!.handler;
    await handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toContain("org-1");
    expect(out).toContain("Acme");
  });

  it("show displays org details", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({ organization_id: "org-1", name: "Acme", slug: "acme", system_count: 2, repo_count: 5 }),
    );
    const handler = orgGroup.getCommand("show")!.handler;
    await handler({ positionals: ["org-1"], values: {} });
    expect(stdout()).toContain("Acme");
  });

  it("delete requires --force", async () => {
    const handler = orgGroup.getCommand("delete")!.handler;
    await expect(handler({ positionals: ["org-1"], values: {} })).rejects.toThrow(CLIError);
  });

  it("delete with --force succeeds", async () => {
    mockFetch.mockResolvedValue(jsonResponse({}));
    const handler = orgGroup.getCommand("delete")!.handler;
    await handler({ positionals: ["org-1"], values: { force: true } });
    expect(stdout()).toContain("deleted");
  });
});
