import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { eventsGroup } from "../../src/commands/events.js";
import { CLIError } from "../../src/framework/errors.js";

describe("events commands", () => {
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

  describe("recent", () => {
    const handler = eventsGroup.getCommand("recent")!.handler;

    it("renders recent events table", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          events: [
            {
              time: "2026-01-01T00:00:00Z",
              event_type: "SessionStarted",
              session_id: "sess-001-abcdef",
              execution_id: "exec-001-abcdef",
            },
          ],
          has_more: false,
        }),
      );

      await handler({ positionals: [], values: {} });
      const out = stdout();
      expect(out).toContain("SessionStarted");
      expect(out).toContain("sess-001-abc");
    });

    it("shows empty message when no events", async () => {
      mockFetch.mockResolvedValue(jsonResponse({ events: [], has_more: false }));
      await handler({ positionals: [], values: {} });
      expect(stdout()).toContain("No recent events");
    });

    it("shows more-available hint", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          events: [{ time: "2026-01-01T00:00:00Z", event_type: "Ev", session_id: "s", execution_id: "e" }],
          has_more: true,
        }),
      );
      await handler({ positionals: [], values: {} });
      expect(stdout()).toContain("--limit");
    });
  });

  describe("session", () => {
    const handler = eventsGroup.getCommand("session")!.handler;

    it("renders session events table", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          events: [
            {
              time: "2026-01-01T00:00:00Z",
              event_type: "ToolStarted",
              phase_id: "phase-001-abcd",
            },
          ],
          has_more: false,
        }),
      );

      await handler({ positionals: ["sess-001"], values: {} });
      const out = stdout();
      expect(out).toContain("ToolStarted");
      expect(out).toContain("phase-001-ab");
    });

    it("shows empty message when no events for session", async () => {
      mockFetch.mockResolvedValue(jsonResponse({ events: [], has_more: false }));
      await handler({ positionals: ["sess-001"], values: {} });
      expect(stdout()).toContain("No events for session");
    });

    it("throws on missing session-id", async () => {
      await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    });
  });

  describe("timeline", () => {
    const handler = eventsGroup.getCommand("timeline")!.handler;

    it("renders timeline table", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse([
          {
            time: "2026-01-01T00:00:00Z",
            event_type: "ToolCompleted",
            tool_name: "Read",
            duration_ms: 150,
            success: true,
          },
        ]),
      );

      await handler({ positionals: ["sess-001"], values: {} });
      const out = stdout();
      expect(out).toContain("ToolCompleted");
      expect(out).toContain("Read");
    });

    it("shows empty message when no entries", async () => {
      mockFetch.mockResolvedValue(jsonResponse([]));
      await handler({ positionals: ["sess-001"], values: {} });
      expect(stdout()).toContain("No timeline entries");
    });

    it("throws on missing session-id", async () => {
      await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    });
  });

  describe("costs", () => {
    const handler = eventsGroup.getCommand("costs")!.handler;

    it("renders cost breakdown", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          session_id: "sess-001",
          input_tokens: 10000,
          output_tokens: 5000,
          total_tokens: 15000,
          cache_creation_tokens: 200,
          cache_read_tokens: 800,
          estimated_cost_usd: "0.15",
        }),
      );

      await handler({ positionals: ["sess-001"], values: {} });
      const out = stdout();
      expect(out).toContain("sess-001");
      expect(out).toContain("10,000");
      expect(out).toContain("5,000");
      expect(out).toContain("15,000");
    });

    it("throws on missing session-id", async () => {
      await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    });
  });

  describe("tools", () => {
    const handler = eventsGroup.getCommand("tools")!.handler;

    it("renders tool usage table", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse([
          {
            tool_name: "Read",
            call_count: 15,
            success_count: 14,
            error_count: 1,
            avg_duration_ms: 120,
          },
          {
            tool_name: "Edit",
            call_count: 8,
            success_count: 8,
            error_count: 0,
            avg_duration_ms: 200,
          },
        ]),
      );

      await handler({ positionals: ["sess-001"], values: {} });
      const out = stdout();
      expect(out).toContain("Read");
      expect(out).toContain("15");
      expect(out).toContain("Edit");
    });

    it("shows empty message when no tool usage", async () => {
      mockFetch.mockResolvedValue(jsonResponse([]));
      await handler({ positionals: ["sess-001"], values: {} });
      expect(stdout()).toContain("No tool usage recorded");
    });

    it("throws on missing session-id", async () => {
      await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    });
  });
});
