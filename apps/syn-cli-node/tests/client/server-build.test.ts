import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { compareReleases, probeServerBuild } from "../../src/client/server-build.js";
import { VERSION_PROBE_TIMEOUT_MS } from "../../src/config.js";

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** The real BuildInfo shape GET /version returns. */
const BUILD = {
  version: "0.33.0b5",
  image_tag: "v0.33.0-beta.5",
  commit: "abc",
  version_status: "installed",
};

describe("compareReleases", () => {
  it.each([
    ["0.33.0-beta.1", "0.33.0b5"], // npm and PEP 440 spell the same beta line
    ["v0.33.0", "0.33.2"],
    ["1.2.0", "1.2.9rc1"],
  ])("%s against %s is the same release line", (cli, server) => {
    expect(compareReleases(cli, server)).toEqual({ kind: "match" });
  });

  it.each([
    ["0.29.0", "0.33.0b5"], // the #1473 incident
    ["0.33.0", "0.34.0"],
    ["0.33.0", "0.3.30"], // a string-prefix compare would call these equal
    ["0.33.0", "0.330.0"],
    ["1.0.0", "0.1.0"],
  ])("%s against %s is a mismatch naming both", (cli, server) => {
    expect(compareReleases(cli, server)).toEqual({ kind: "mismatch", cli, server });
  });

  it.each([
    ["a dev CLI", "0.0.0-dev", "0.33.0b5"],
    ["a server that cannot read its release", "0.33.0", null],
    ["an unparseable CLI version", "garbage", "0.33.0"],
    ["an unparseable server version", "0.33.0", "unknown"],
  ])("%s is undetermined, never a mismatch", (_case, cli, server) => {
    expect(compareReleases(cli, server)).toEqual({ kind: "undetermined" });
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

  it("reports the build GET /api/v1/version returned", async () => {
    mockFetch.mockResolvedValue(jsonResponse(BUILD));

    expect(await probeServerBuild()).toEqual({ kind: "reported", build: BUILD });
    const request = mockFetch.mock.calls[0]![0] as Request;
    expect(new URL(request.url).pathname).toBe("/api/v1/version");
  });

  // Blocker 2 of the #1473 review: a 404 proves nothing about the release.
  it("treats a 404 as unanswered, not as an old release", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ detail: "Not Found" }, 404));

    const result = await probeServerBuild();

    expect(result.kind).toBe("unanswered");
    expect(result.kind === "unanswered" && result.reason).toContain("no GET /version");
  });

  it.each([
    ["an unreachable server", () => Promise.reject(new TypeError("fetch failed")), "fetch failed"],
    ["a 401", () => Promise.resolve(jsonResponse({ detail: "Unauthorized" }, 401)), "401"],
    [
      "an HTML body on 200",
      () => Promise.resolve(new Response("<html>", { status: 200, headers: { "Content-Type": "application/json" } })),
      "",
    ],
  ])("never throws for %s", async (_case, respond, reason) => {
    mockFetch.mockImplementation(respond);

    const result = await probeServerBuild();

    expect(result.kind).toBe("unanswered");
    expect(result.kind === "unanswered" && result.reason).toContain(reason);
  });

  it("gives up after VERSION_PROBE_TIMEOUT_MS on a server that never answers", async () => {
    vi.useFakeTimers();
    // Settles only when the probe aborts, so a dropped signal hangs this test.
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
