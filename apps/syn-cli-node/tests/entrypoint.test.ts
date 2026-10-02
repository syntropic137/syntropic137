/**
 * The CLI as shipped: `src/index.ts`, imported for real, with process.argv
 * set the way a shell would set it (#1473, review blocker 3).
 *
 * The framework tests build their own CLI with their own preflight, so they
 * would stay green if the shipped entrypoint never installed the version
 * check at all. This is the incident's regression test: an old CLI, a newer
 * server, `syn workflow run <unknown>`, and the warning must come first.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/config.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/config.js")>()),
  CLI_VERSION: "0.29.0",
}));

describe("the shipped syn entrypoint", () => {
  const events: string[] = [];
  const originalArgv = process.argv;
  let exitSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    events.length = 0;
    vi.resetModules();
    exitSpy = vi
      .spyOn(process, "exit")
      .mockImplementation((() => {}) as unknown as (code?: number) => never);
    // One list for both streams, so order across stdout and stderr survives.
    vi.spyOn(process.stdout, "write").mockImplementation((c: unknown) => (events.push(String(c)), true));
    vi.spyOn(process.stderr, "write").mockImplementation((c: unknown) => (events.push(String(c)), true));
  });

  afterEach(() => {
    process.argv = originalArgv;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  function json(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  /** A server with no workflow `nope`, answering /version as `version` says. */
  function serve(version: () => Promise<Response>): void {
    vi.stubGlobal("fetch", (request: Request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/v1/version") return version();
      if (path === "/api/v1/workflows") return Promise.resolve(json({ workflows: [], total: 0 }));
      return Promise.resolve(json({ detail: "Workflow not found" }, 404));
    });
  }

  async function synWorkflowRunNope(): Promise<(needle: string) => number> {
    process.argv = ["node", "syn", "workflow", "run", "nope"];
    await import("../src/index.js");
    await vi.waitFor(() => expect(exitSpy).toHaveBeenCalled());
    expect(exitSpy).toHaveBeenCalledWith(1);
    return (needle) => events.findIndex((e) => e.includes(needle));
  }

  it("warns about a newer server before the command's own error", async () => {
    serve(async () => json({ version: "0.33.0b5", image_tag: null, commit: null, version_status: "installed" }));
    const at = await synWorkflowRunNope();

    expect(at("Warning:")).toBeGreaterThanOrEqual(0);
    expect(events[at("Warning:")]).toContain("0.29.0");
    expect(events[at("Warning:")]).toContain("0.33.0b5");
    expect(at("No workflow found matching: nope")).toBeGreaterThan(at("Warning:"));
  });

  it("says nothing when the server is on the same release line", async () => {
    serve(async () => json({ version: "0.29.1", image_tag: null, commit: null, version_status: "installed" }));
    const at = await synWorkflowRunNope();

    expect(at("Warning:")).toBe(-1);
    expect(at("No workflow found matching: nope")).toBeGreaterThanOrEqual(0);
  });

  it.each<[string, () => Promise<Response>]>([
    ["unreachable", () => Promise.reject(new TypeError("fetch failed"))],
    ["404 (no /version route)", async () => json({ detail: "Not Found" }, 404)],
  ])("says nothing, and lets the command speak, when /version is %s", async (_label, version) => {
    serve(version);
    const at = await synWorkflowRunNope();

    expect(at("Warning:")).toBe(-1);
    expect(at("No workflow found matching: nope")).toBeGreaterThanOrEqual(0);
  });
});
