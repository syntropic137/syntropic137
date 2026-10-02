import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// CLI_VERSION is 0.0.0-dev under vitest, which is never compared. Pin a real
// release so the comparison actually runs.
vi.mock("../../src/config.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/config.js")>()),
  CLI_VERSION: "0.29.0",
}));

const { versionCommand } = await import("../../src/commands/version.js");

describe("version command", () => {
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

  function written(stream: NodeJS.WriteStream): string {
    return (stream.write as ReturnType<typeof vi.fn>).mock.calls
      .map((c: unknown[]) => String(c[0]))
      .join("");
  }

  function json(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  const build = (version: string) => ({
    version,
    image_tag: "v0.29.3",
    commit: "9f3c1ab",
    version_status: "installed",
  });

  async function run(): Promise<{ lines: string[]; stderr: string }> {
    await versionCommand.handler({ positionals: [], values: {} });
    return { lines: written(process.stdout).split("\n"), stderr: written(process.stderr) };
  }

  it("prints the CLI on line 1 and the server build on line 2", async () => {
    mockFetch.mockResolvedValue(json(build("0.29.3")));
    const { lines, stderr } = await run();
    expect(lines[0]).toContain("Syntropic137 v0.29.0");
    expect(lines[1]).toBe("syn-api 0.29.3 (v0.29.3, 9f3c1ab)");
    expect(stderr).not.toContain("Warning");
  });

  it("warns on stderr when the release lines differ", async () => {
    mockFetch.mockResolvedValue(json(build("0.33.0b5")));
    const { lines, stderr } = await run();
    expect(lines[1]).toContain("syn-api 0.33.0b5");
    expect(stderr).toContain("Warning:");
    expect(stderr).toContain("0.29.0");
    expect(stderr).toContain("0.33.0b5");
  });

  it("still reports the CLI, and exits cleanly, when the server is unreachable", async () => {
    mockFetch.mockRejectedValue(new TypeError("fetch failed"));
    const { lines, stderr } = await run();
    expect(lines[0]).toContain("Syntropic137 v0.29.0");
    expect(lines[1]).toContain("syn-api not reached at http");
    expect(lines[1]).toContain("fetch failed");
    expect(stderr).not.toContain("Warning");
  });

  it("names a server with no /version route without calling it a mismatch", async () => {
    mockFetch.mockResolvedValue(json({ detail: "Not Found" }, 404));
    const { lines, stderr } = await run();
    expect(lines[1]).toContain("has no GET /version");
    expect(stderr).not.toContain("Warning");
  });
});
