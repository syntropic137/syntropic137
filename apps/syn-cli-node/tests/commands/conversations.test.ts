import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { conversationsGroup } from "../../src/commands/conversations.js";
import { CLIError } from "../../src/framework/errors.js";

describe("conversations commands", () => {
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

  describe("show", () => {
    const handler = conversationsGroup.getCommand("show")!.handler;

    it("renders conversation lines table", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          lines: [
            {
              line_number: 1,
              event_type: "assistant",
              tool_name: "Read",
              content_preview: "Reading file...",
            },
            {
              line_number: 2,
              event_type: "tool_result",
              tool_name: "Read",
              content_preview: "File contents here",
            },
          ],
          total_lines: 50,
        }),
      );

      await handler({ positionals: ["session-abc-123"], values: {} });
      const out = stdout();
      expect(out).toContain("session-abc-123");
      expect(out).toContain("assistant");
      expect(out).toContain("Read");
      expect(out).toContain("Reading file...");
    });

    it("shows empty message when no lines", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({ lines: [], total_lines: 0 }),
      );
      await handler({ positionals: ["session-abc-123"], values: {} });
      expect(stdout()).toContain("No conversation lines found");
    });

    it("shows pagination hint when more lines available", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          lines: [{ line_number: 1, event_type: "assistant", tool_name: null, content_preview: "hi" }],
          total_lines: 200,
        }),
      );

      await handler({ positionals: ["session-abc-123"], values: {} });
      expect(stdout()).toContain("--offset");
    });

    it("throws on missing session-id", async () => {
      await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    });
  });

  describe("metadata", () => {
    const handler = conversationsGroup.getCommand("metadata")!.handler;

    it("renders metadata summary", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          session_id: "sess-001",
          model: "claude-sonnet-4-20250514",
          event_count: 42,
          total_input_tokens: 10000,
          total_output_tokens: 5000,
          started_at: "2026-01-01T00:00:00Z",
          completed_at: "2026-01-01T01:00:00Z",
          size_bytes: 8192,
          tool_counts: { Read: 10, Edit: 5, Bash: 3 },
        }),
      );

      await handler({ positionals: ["sess-001"], values: {} });
      const out = stdout();
      expect(out).toContain("sess-001");
      expect(out).toContain("claude-sonnet-4-20250514");
      expect(out).toContain("10,000");
      expect(out).toContain("5,000");
      expect(out).toContain("Read");
    });

    it("throws on missing session-id", async () => {
      await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    });

    it("throws when session not found", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({ detail: "No metadata found for session: nonexistent" }, 404),
      );
      await expect(
        handler({ positionals: ["nonexistent"], values: {} }),
      ).rejects.toThrow(CLIError);
    });
  });
});
