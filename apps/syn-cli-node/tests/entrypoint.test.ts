/**
 * The shipped CLI warns about release skew before a command's own error (#1473).
 *
 * Imports the real entrypoint, src/index.ts, rather than building a CLI here:
 * the framework tests prove the hook works when it is passed, and only this
 * proves `syn` passes it. Dropping the preflight from index.ts leaves every
 * other test green and brings back the incident: a 0.29 CLI against a 0.33
 * server printing "No workflow found" with nothing pointing at the versions.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const cliVersion = vi.hoisted(() => ({ value: "0.29.0" }));
vi.mock("../src/config.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/config.js")>()),
  get CLI_VERSION() {
    return cliVersion.value;
  },
}));

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** A server at `serverVersion` that knows no workflows. `null` means
 * GET /version itself fails to connect. */
function server(serverVersion: string | null) {
  return async (request: Request): Promise<Response> => {
    const { pathname } = new URL(request.url);
    if (pathname === "/api/v1/version") {
      if (serverVersion === null) throw new TypeError("fetch failed");
      return jsonResponse({
        version: serverVersion,
        image_tag: null,
        commit: null,
        version_status: "installed",
      });
    }
    if (pathname === "/api/v1/workflows") return jsonResponse({ workflows: [], total: 0 });
    return jsonResponse({ detail: "Not Found" }, 404);
  };
}

// The first test transforms the whole CLI module graph (every command) on a
// cold import: ~4s alone and more under the parallel suite, which raced
// vitest's 5s default. The time is the import, not the behaviour under test.
const COLD_IMPORT_MS = 30_000;

describe("syn entrypoint (src/index.ts)", { timeout: COLD_IMPORT_MS }, () => {
  const events: string[] = [];
  let exitSpy: ReturnType<typeof vi.spyOn>;
  const argv = process.argv;

  beforeEach(() => {
    events.length = 0;
    vi.resetModules();
    exitSpy = vi
      .spyOn(process, "exit")
      .mockImplementation((() => {}) as unknown as (code?: number) => never);
    // One list for both streams, so the order across them is preserved.
    vi.spyOn(process.stdout, "write").mockImplementation((chunk) => (events.push(String(chunk)), true));
    vi.spyOn(process.stderr, "write").mockImplementation((chunk) => (events.push(String(chunk)), true));
    process.argv = ["node", "syn", "workflow", "run", "nope"];
  });

  afterEach(() => {
    process.argv = argv;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  async function runSyn(fetchImpl: (request: Request) => Promise<Response>): Promise<void> {
    vi.stubGlobal("fetch", vi.fn(fetchImpl));
    await import("../src/index.js");
    // index.ts does not await cli.run(); the exit call is where it finishes.
    await vi.waitFor(() => expect(exitSpy).toHaveBeenCalled(), { timeout: COLD_IMPORT_MS });
  }

  const at = (text: string) => events.findIndex((e) => e.includes(text));

  it("warns about the release skew before `workflow run` reports its own error", async () => {
    cliVersion.value = "0.29.0";

    await runSyn(server("0.33.0b5"));

    expect(at("Warning:")).toBeGreaterThanOrEqual(0);
    expect(events[at("Warning:")]).toContain("0.29.0");
    expect(events[at("Warning:")]).toContain("0.33.0b5");
    expect(at("Warning:")).toBeLessThan(at("No workflow found matching: nope"));
    expect(exitSpy).toHaveBeenCalledWith(1);
  });

  it("says nothing extra when the release lines match", async () => {
    cliVersion.value = "0.29.0";

    await runSyn(server("0.29.1"));

    expect(at("Warning:")).toBe(-1);
    expect(at("No workflow found matching: nope")).toBeGreaterThanOrEqual(0);
  });

  it("stays out of the way when GET /version cannot be reached", async () => {
    cliVersion.value = "0.29.0";

    await runSyn(server(null));

    expect(at("Warning:")).toBe(-1);
    expect(at("No workflow found matching: nope")).toBeGreaterThanOrEqual(0);
  });
});
