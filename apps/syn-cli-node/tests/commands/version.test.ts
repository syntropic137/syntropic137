import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// CLI_VERSION is 0.0.0-dev under vitest, which compares as undetermined; a
// real release number is the only way to reach match or mismatch.
const cliVersion = vi.hoisted(() => ({ value: "0.33.0-beta.1" }));
vi.mock("../../src/config.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/config.js")>()),
  get CLI_VERSION() {
    return cliVersion.value;
  },
}));

const { versionCommand } = await import("../../src/commands/version.js");

describe("version command", () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
    vi.spyOn(process.stdout, "write").mockReturnValue(true);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
    cliVersion.value = "0.33.0-beta.1";
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

  function jsonResponse(data: unknown, status = 200): Response {
    return new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  const BUILD = {
    version: "0.33.0b5",
    image_tag: "v0.33.0-beta.5",
    commit: "abc",
    version_status: "installed",
  };

  const run = () => versionCommand.handler({ positionals: [], values: {} });

  it("reports the CLI on line 1 and the server build on line 2", async () => {
    mockFetch.mockResolvedValue(jsonResponse(BUILD));

    await run();

    const lines = written(process.stdout).split("\n");
    expect(lines[0]).toContain("Syntropic137 v0.33.0-beta.1");
    expect(lines[1]).toContain("syn-api 0.33.0b5 (v0.33.0-beta.5, abc)");
    expect(written(process.stderr)).not.toContain("Warning");
  });

  it("warns on stderr when the release lines differ", async () => {
    cliVersion.value = "0.29.0";
    mockFetch.mockResolvedValue(jsonResponse(BUILD));

    await run();

    const err = written(process.stderr);
    expect(err).toContain("Warning:");
    expect(err).toContain("0.29.0");
    expect(err).toContain("0.33.0b5");
  });

  it("still reports the CLI, without throwing or warning, when the server is unreachable", async () => {
    mockFetch.mockRejectedValue(new TypeError("fetch failed"));

    await run();

    const lines = written(process.stdout).split("\n");
    expect(lines[0]).toContain("Syntropic137 v");
    expect(lines[1]).toContain("syn-api not identified at");
    expect(lines[1]).toContain("fetch failed");
    expect(written(process.stderr)).not.toContain("Warning");
  });

  it("names a server with no GET /version without calling it a mismatch", async () => {
    cliVersion.value = "0.29.0";
    mockFetch.mockResolvedValue(jsonResponse({ detail: "Not Found" }, 404));

    await run();

    expect(written(process.stdout).split("\n")[1]).toContain("no GET /version");
    expect(written(process.stderr)).not.toContain("Warning");
  });
});
