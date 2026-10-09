import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { observabilityGroup } from "../../src/commands/observability.js";

describe("observability commands", () => {
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

  it("latency prints the recorder's drop counters even when no rows were recorded", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        window: "24h",
        since: "2026-10-07T00:00:00+00:00",
        available: true,
        routes: [],
        recorder: { running: false, written: 0, dropped: 42, write_failures: 3, discarded: 5, cleanup_failures: 2, buffered: 0 },
      }),
    );

    await observabilityGroup.getCommand("latency")!.handler({ positionals: [], values: { window: "24h" } });
    const out = stdout();
    expect(out).toContain("NOT running");
    expect(out).toContain("42 dropped");
    expect(out).toContain("3 failed writes");
    expect(out).toContain("5 discarded");
    expect(out).toContain("2 connection cleanups failed");
  });

  it("latency prints one row per route", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        window: "7d",
        since: "2026-10-01T00:00:00+00:00",
        available: true,
        routes: [
          { method: "GET", route: "/evals", count: 12, p50_ms: 40, p95_ms: 900, p99_ms: 24500, max_ms: 26000, p99_display: "24.5 s" },
        ],
        recorder: { running: true, written: 12, dropped: 0, write_failures: 0, discarded: 0, cleanup_failures: 0, buffered: 0 },
      }),
    );

    await observabilityGroup.getCommand("latency")!.handler({ positionals: [], values: { window: "7d" } });
    const out = stdout();
    expect(out).toContain("/evals");
    expect(out).toContain("24500");
    expect(out).toContain("arrival to response start");
    expect(out).not.toContain("dropped");
  });
});
