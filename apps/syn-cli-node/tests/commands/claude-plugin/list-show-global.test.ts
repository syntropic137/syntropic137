import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { claudePluginGroup } from "../../../src/commands/claude-plugin/index.js";
import { CLIError } from "../../../src/framework/errors.js";

describe("claude-plugin list/show/global", () => {
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

  describe("list", () => {
    const handler = claudePluginGroup.getCommand("list")!.handler;

    it("renders empty message when no plugins", async () => {
      mockFetch.mockResolvedValue(jsonResponse({ plugins: [], total: 0 }));
      await handler({ positionals: [], values: {} });
      expect(stdout()).toContain("No claude plugins registered");
    });

    it("renders table of registered plugins", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          plugins: [
            {
              name: "software-leverage-points",
              source_url: "https://github.com/syntropic137/software-leverage-points",
              version: "5.0.7",
              resolved_sha: "a1b2c3d4e5f6abcdef",
              tree_storage_prefix: "claude-plugins/sha256-a1b2.../",
              registered_at: "2026-05-05T14:55:00Z",
            },
          ],
          total: 1,
        }),
      );
      await handler({ positionals: [], values: {} });
      const out = stdout();
      expect(out).toContain("software-leverage-points");
      expect(out).toContain("5.0.7");
    });
  });

  describe("show", () => {
    const handler = claudePluginGroup.getCommand("show")!.handler;

    it("renders plugin detail", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          name: "software-leverage-points",
          source_url: "https://github.com/syntropic137/software-leverage-points",
          version: "5.0.7",
          resolved_sha: "a1b2c3d4e5f6abcdef",
          tree_storage_prefix: "claude-plugins/sha256-a1b2.../",
          registered_at: "2026-05-05T14:55:00Z",
        }),
      );
      await handler({ positionals: ["software-leverage-points", "5.0.7"], values: {} });
      const out = stdout();
      expect(out).toContain("software-leverage-points");
      expect(out).toContain("a1b2c3d4e5f6abcdef");
    });

    it("throws on missing name", async () => {
      await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    });

    it("throws on missing version", async () => {
      await expect(handler({ positionals: ["only-name"], values: {} })).rejects.toThrow(CLIError);
    });
  });

  describe("global", () => {
    const handler = claudePluginGroup.getCommand("global")!.handler;

    it("requires a subaction", async () => {
      await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    });

    it("rejects unknown subactions", async () => {
      await expect(
        handler({ positionals: ["frobnicate"], values: {} }),
      ).rejects.toThrow(CLIError);
    });

    it("add: requires name and version", async () => {
      await expect(
        handler({ positionals: ["add"], values: {} }),
      ).rejects.toThrow(CLIError);
      await expect(
        handler({ positionals: ["add", "only-name"], values: {} }),
      ).rejects.toThrow(CLIError);
    });

    it("add: succeeds for an already-registered plugin", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse(
          {
            name: "software-leverage-points",
            source_url: "https://github.com/syntropic137/software-leverage-points",
            version: "5.0.7",
            resolved_sha: "a1b2c3d4e5f6deadbeef",
            added_at: "2026-05-05T14:55:00Z",
          },
          201,
        ),
      );
      await handler({
        positionals: ["add", "software-leverage-points", "5.0.7"],
        values: {},
      });
      const out = stdout();
      expect(out).toContain("Added software-leverage-points@5.0.7 to global plugin set");
    });

    it("add: produces helpful error when plugin not registered (404)", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse(
          {
            detail: {
              error_code: "claude_plugin_not_registered",
              message: "Plugin not registered",
              name: "missing",
              version: "1.0.0",
            },
          },
          404,
        ),
      );
      await expect(
        handler({ positionals: ["add", "missing", "1.0.0"], values: {} }),
      ).rejects.toThrow(/not registered.*Install it first/s);
    });

    it("remove: requires name", async () => {
      await expect(
        handler({ positionals: ["remove"], values: {} }),
      ).rejects.toThrow(CLIError);
    });

    it("remove: prints confirmation", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({ name: "software-leverage-points", status: "removed" }),
      );
      await handler({
        positionals: ["remove", "software-leverage-points"],
        values: {},
      });
      expect(stdout()).toContain("Removed software-leverage-points from global plugin set");
    });

    it("list: empty state", async () => {
      mockFetch.mockResolvedValue(jsonResponse({ plugins: [], total: 0 }));
      await handler({ positionals: ["list"], values: {} });
      expect(stdout()).toContain("No global claude plugins");
    });

    it("list: renders table", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          plugins: [
            {
              name: "software-leverage-points",
              source_url: "https://github.com/syntropic137/software-leverage-points",
              version: "5.0.7",
              resolved_sha: "a1b2c3",
              added_at: "2026-05-05T14:55:00Z",
            },
          ],
          total: 1,
        }),
      );
      await handler({ positionals: ["list"], values: {} });
      const out = stdout();
      expect(out).toContain("software-leverage-points");
      expect(out).toContain("5.0.7");
    });
  });
});
