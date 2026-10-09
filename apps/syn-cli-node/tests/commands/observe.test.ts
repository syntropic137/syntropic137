import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { observeGroup } from "../../src/commands/observe.js";
import { CLIError } from "../../src/framework/errors.js";

describe("observe commands", () => {
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

  describe("tools", () => {
    it("renders tool timeline table", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          executions: [
            {
              time: "2026-01-01T00:00:00Z",
              tool_name: "Read",
              duration_ms: 150,
              success: true,
            },
            {
              time: "2026-01-01T00:00:01Z",
              tool_name: "Write",
              duration_ms: 320,
              success: false,
            },
          ],
        }),
      );

      await observeGroup
        .getCommand("tools")!
        .handler({ positionals: ["sess-abc-123"], values: {} });

      const out = stdout();
      expect(out).toContain("Read");
      expect(out).toContain("Write");
      expect(out).toContain("Tool Timeline");
    });

    it("shows empty message when no entries", async () => {
      mockFetch.mockResolvedValue(jsonResponse({ executions: [] }));

      await observeGroup
        .getCommand("tools")!
        .handler({ positionals: ["sess-abc-123"], values: {} });

      expect(stdout()).toContain("No tool timeline entries");
    });

    it("throws CLIError when session-id is missing", async () => {
      await expect(
        observeGroup
          .getCommand("tools")!
          .handler({ positionals: [], values: {} }),
      ).rejects.toThrow(CLIError);
    });
  });

  describe("tokens", () => {
    it("renders token metrics", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          session_id: "sess-abc-123",
          input_tokens: 8000,
          output_tokens: 2000,
          total_tokens: 10000,
          cache_creation_tokens: 500,
          cache_read_tokens: 300,
          total_cost_usd: "0.12",
        }),
      );

      await observeGroup
        .getCommand("tokens")!
        .handler({ positionals: ["sess-abc-123"], values: {} });

      const out = stdout();
      expect(out).toContain("sess-abc-123");
      expect(out).toContain("Input tokens");
      expect(out).toContain("Output tokens");
      expect(out).toContain("Total tokens");
      expect(out).toContain("Cache creation");
      expect(out).toContain("Cache read");
      expect(out).toContain("Estimated cost");
    });

    it("throws CLIError when session-id is missing", async () => {
      await expect(
        observeGroup
          .getCommand("tokens")!
          .handler({ positionals: [], values: {} }),
      ).rejects.toThrow(CLIError);
    });
  });
});

describe("observe latency", () => {
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

    await observeGroup.getCommand("latency")!.handler({ positionals: [], values: { window: "24h" } });
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

    await observeGroup.getCommand("latency")!.handler({ positionals: [], values: { window: "7d" } });
    const out = stdout();
    expect(out).toContain("/evals");
    expect(out).toContain("24500");
    expect(out).toContain("arrival to response start");
    expect(out).not.toContain("dropped");
  });
});
