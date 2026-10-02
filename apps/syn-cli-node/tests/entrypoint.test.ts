/**
 * The CLI as shipped: `src/index.ts`, imported for real, with process.argv
 * set the way a shell would set it (#1473, review blocker 3).
 *
 * The framework tests build their own CLI with their own preflight, so they
 * would stay green if the shipped entrypoint never installed the version
 * check at all. This is the incident's regression test: an old CLI, a newer
 * server, `syn workflow run <unknown>`, and the warning must come first.
 */
import { readFileSync } from "node:fs";
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
    ["a 200 whose JSON body is null", async () => json(null)],
  ])("says nothing, and lets the command speak, when /version is %s", async (_label, version) => {
    serve(version);
    const at = await synWorkflowRunNope();

    expect(at("Warning:")).toBe(-1);
    expect(at("No workflow found matching: nope")).toBeGreaterThanOrEqual(0);
  });

  /** `GET /api/v1/executions/exec-b6f4c2b271d0` as the VPS answered it
   * (operations trimmed): completed, deliverable stored, write-back denied. */
  const deniedRun: unknown = JSON.parse(
    readFileSync(new URL("./fixtures/execution-detail-exec-b6f4c2b271d0.json", import.meta.url), "utf8"),
  );

  /** A 0.33.0b5 server that predates session inventory: the router 404s it,
   * exactly as the VPS does. Counts every /version request. */
  function serveBeta5(): { versionRequests: () => number } {
    let versionRequests = 0;
    vi.stubGlobal("fetch", async (request: Request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/v1/version") {
        versionRequests++;
        return json({ version: "0.33.0b5", image_tag: null, commit: null, version_status: "installed" });
      }
      if (path === "/api/v1/executions/exec-b6f4c2b271d0") return json(deniedRun);
      return json({ detail: "Not Found" }, 404);
    });
    return { versionRequests: () => versionRequests };
  }

  const plain = (): string => events.join("").replace(/\x1b\[[0-9;]*m/g, "");

  it("renders the execution outcome in `syn execution show` (#1501 A)", async () => {
    serveBeta5();
    process.argv = ["node", "syn", "execution", "show", "exec-b6f4c2b271d0"];
    await import("../src/index.js");
    await vi.waitFor(() => expect(plain()).toContain("Session inventory"));

    expect(plain()).toContain("  Deliverable:  yes\n");
    expect(plain()).toContain("  Side effects: denied\n");
    expect(plain().split("\n").find((l) => l.includes("Review the PR"))).toMatch(/denied\s*$/);
  });

  it("names the server build when a known route is missing, after the skew warning (#1501 B)", async () => {
    const server = serveBeta5();
    process.argv = ["node", "syn", "execution", "sessions", "exec-b6f4c2b271d0"];
    await import("../src/index.js");
    await vi.waitFor(() => expect(exitSpy).toHaveBeenCalled());
    expect(exitSpy).toHaveBeenCalledWith(1);

    const at = (needle: string) => events.findIndex((e) => e.includes(needle));
    const error = events[at("Failed to read session inventory")] ?? "";
    expect(error).toContain("syn-api 0.33.0b5");
    expect(error).toContain("has no GET /executions/{execution_id}/session-inventory; this server predates the feature");
    expect(error).not.toContain(": Not Found");
    // #1494's order holds: the warning (0.29.0 CLI, 0.33 server) comes first.
    expect(at("Warning:")).toBeGreaterThanOrEqual(0);
    expect(at("Failed to read session inventory")).toBeGreaterThan(at("Warning:"));
    // The explanation reuses the preflight's answer rather than asking again.
    expect(server.versionRequests()).toBe(1);
  });
});
