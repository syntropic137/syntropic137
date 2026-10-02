import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  compareReleases,
  probeServerBuild,
  type ServerBuild,
} from "../../src/client/server-build.js";
import { VERSION_PROBE_TIMEOUT_MS } from "../../src/config.js";

/** The shape GET /version really returns (BuildInfo). */
function reported(version: string | null): ServerBuild {
  return {
    kind: "reported",
    build: {
      version,
      image_tag: "v0.33.0-beta.5",
      commit: "abc",
      version_status: version === null ? "unavailable" : "installed",
    },
  };
}

describe("compareReleases", () => {
  it.each([
    ["0.33.0-beta.1", "0.33.0b5"],
    ["v0.33.0", "0.33.2"],
    ["1.2.0", "1.2.9rc1"],
  ])("%s against %s is the same release line", (cli, server) => {
    expect(compareReleases(cli, reported(server))).toEqual({ kind: "match" });
  });

  it.each([
    ["0.29.0", "0.33.0b5", "0.29", "0.33"],
    ["0.33.0", "0.34.0", "0.33", "0.34"],
    // A string-prefix compare would call both of these a match.
    ["0.33.0", "0.3.30", "0.33", "0.3"],
    ["0.33.0", "0.330.0", "0.33", "0.330"],
    ["1.0.0", "0.1.0", "1.0", "0.1"],
  ])("%s against %s is a mismatch", (cli, server, cliLine, serverLine) => {
    expect(compareReleases(cli, reported(server))).toEqual({
      kind: "mismatch",
      cli,
      server,
      cliLine,
      serverLine,
    });
  });

  it.each<[string, string, ServerBuild]>([
    ["a dev CLI", "0.0.0-dev", reported("0.33.0b5")],
    ["a server that cannot read its release", "0.29.0", reported(null)],
    ["an unparseable CLI version", "garbage", reported("0.33.0b5")],
    ["an unparseable server version", "0.29.0", reported("latest")],
    // #1473 review blocker 2: a 404 compares nothing. The server may be the
    // same release line and older than the route, or not syn-api at all.
    ["a server with no /version route", "0.29.0", { kind: "no-version-route" }],
    ["an unreachable server", "0.29.0", { kind: "unanswered", reason: "fetch failed" }],
  ])("%s is undetermined, never a mismatch", (_label, cli, server) => {
    expect(compareReleases(cli, server)).toEqual({ kind: "undetermined" });
  });

  it("does not trust the schema for the server's version field", () => {
    const odd = { kind: "reported", build: { version: 33 } } as unknown as ServerBuild;
    expect(compareReleases("0.29.0", odd)).toEqual({ kind: "undetermined" });
  });
});

describe("probeServerBuild", () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.resetAllMocks();
    vi.unstubAllGlobals();
  });

  function json(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  it("reports the build from GET /api/v1/version", async () => {
    const build = { version: "0.33.0b5", image_tag: "v0.33.0-beta.5", commit: "abc", version_status: "installed" };
    mockFetch.mockResolvedValue(json(build));

    expect(await probeServerBuild()).toEqual({ kind: "reported", build });
    const request = mockFetch.mock.calls[0]![0] as Request;
    expect(new URL(request.url).pathname).toBe("/api/v1/version");
  });

  it("reads a 404 as a server with no /version route", async () => {
    mockFetch.mockResolvedValue(json({ detail: "Not Found" }, 404));
    expect(await probeServerBuild()).toEqual({ kind: "no-version-route" });
  });

  it.each<[string, () => Promise<Response>]>([
    ["an unreachable server", () => Promise.reject(new TypeError("fetch failed"))],
    ["a 401", () => Promise.resolve(json({ detail: "Unauthorized" }, 401))],
    ["an HTML 200 from a proxy", () => Promise.resolve(new Response("<html>", { status: 200, headers: { "Content-Type": "application/json" } }))],
  ])("turns %s into unanswered rather than throwing", async (_label, respond) => {
    mockFetch.mockImplementation(respond);
    const result = await probeServerBuild();
    expect(result.kind).toBe("unanswered");
  });

  it("gives up after VERSION_PROBE_TIMEOUT_MS instead of holding the command", async () => {
    vi.useFakeTimers();
    // Settles ONLY when the request is aborted, so a probe that dropped its
    // signal would never resolve and this test would time out.
    mockFetch.mockImplementation(
      (request: Request) =>
        new Promise((_resolve, reject) => {
          request.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );

    const pending = probeServerBuild();
    await vi.advanceTimersByTimeAsync(VERSION_PROBE_TIMEOUT_MS);

    expect(await pending).toEqual({
      kind: "unanswered",
      reason: `no answer within ${VERSION_PROBE_TIMEOUT_MS}ms`,
    });
  });
});
