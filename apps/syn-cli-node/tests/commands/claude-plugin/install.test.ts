import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// vi.mock the git module BEFORE importing the install command so the
// command picks up the stub during module evaluation.
vi.mock("../../../src/packages/git.js", async () => {
  const realFs = await import("node:fs");
  const realOs = await import("node:os");
  const realPath = await import("node:path");
  return {
    gitClone: vi.fn(async (_url: string, _ref: string, destDir: string) => {
      // Lay down a minimal valid plugin tree for the install flow to walk.
      const pluginDir = realPath.join(destDir, ".claude-plugin");
      realFs.mkdirSync(pluginDir, { recursive: true });
      realFs.writeFileSync(
        realPath.join(pluginDir, "plugin.json"),
        JSON.stringify({ name: "fixture-plugin", version: "0.0.1" }) + "\n",
        "utf-8",
      );
      realFs.writeFileSync(
        realPath.join(destDir, "README.md"),
        "# fixture\n",
        "utf-8",
      );
    }),
    gitLsRemote: vi.fn(async () => null),
    makeTempDir: (prefix: string) =>
      realFs.mkdtempSync(realPath.join(realOs.tmpdir(), prefix)),
    removeTempDir: (dir: string) =>
      realFs.rmSync(dir, { recursive: true, force: true }),
  };
});

import { claudePluginGroup } from "../../../src/commands/claude-plugin/index.js";
import { CLIError } from "../../../src/framework/errors.js";
import { registryPath } from "../../../src/packages/claude-plugin-registry.js";

describe("claude-plugin install", () => {
  const mockFetch = vi.fn();

  function clearRegistry(): void {
    const p = registryPath();
    if (fs.existsSync(p)) fs.rmSync(p);
  }

  beforeEach(() => {
    clearRegistry();
    vi.stubGlobal("fetch", mockFetch);
    vi.spyOn(process.stdout, "write").mockReturnValue(true);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    clearRegistry();
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

  const handler = claudePluginGroup.getCommand("install")!.handler;

  it("requires a ref", async () => {
    await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
  });

  it("rejects unparseable refs before any network call", async () => {
    await expect(
      handler({ positionals: ["not a real ref"], values: {} }),
    ).rejects.toThrow(CLIError);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("clones, walks, and POSTs registration (no --global)", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(
        {
          name: "fixture-plugin",
          version: "main",
          sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        },
        201,
      ),
    );
    await handler({
      positionals: ["acme/fixture-plugin@main"],
      values: {},
    });
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const req = mockFetch.mock.calls[0]![0] as Request;
    expect(req.url).toContain("/claude-plugins/registrations");
    expect(req.method).toBe("POST");
    const body = JSON.parse(await req.text()) as {
      source_url: string;
      version: string;
      name: string;
      manifest: { name: string };
      files: { rel_path: string; content_b64: string }[];
    };
    expect(body.source_url).toBe("https://github.com/acme/fixture-plugin");
    expect(body.version).toBe("main");
    expect(body.name).toBe("fixture-plugin");
    expect(body.manifest.name).toBe("fixture-plugin");
    const relPaths = body.files.map((f) => f.rel_path).sort();
    expect(relPaths).toEqual([".claude-plugin/plugin.json", "README.md"]);
    const out = stdout();
    expect(out).toContain("Registered");
    expect(out).toContain("fixture-plugin");
    expect(out).toContain("0123456789ab");
  });

  it("with --global, fires both register and global-add POSTs in order", async () => {
    mockFetch
      .mockResolvedValueOnce(
        jsonResponse(
          {
            name: "fixture-plugin",
            version: "v1",
            sha256: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
          },
          201,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          {
            name: "fixture-plugin",
            source_url: "https://github.com/acme/fixture-plugin",
            version: "v1",
            resolved_sha: "deadbeefdeadbeef",
            added_at: "2026-05-05T14:55:00Z",
          },
          201,
        ),
      );
    await handler({
      positionals: ["acme/fixture-plugin@v1"],
      values: { global: true },
    });
    expect(mockFetch).toHaveBeenCalledTimes(2);
    const firstReq = mockFetch.mock.calls[0]![0] as Request;
    const secondReq = mockFetch.mock.calls[1]![0] as Request;
    expect(firstReq.url).toContain("/claude-plugins/registrations");
    expect(secondReq.url).toContain("/claude-plugins/global");
    const out = stdout();
    expect(out).toContain("Added fixture-plugin to global plugin set");
  });

  it("rejects @latest as a version", async () => {
    await expect(
      handler({ positionals: ["acme/fixture-plugin@latest"], values: {} }),
    ).rejects.toThrow(/latest.*not allowed/i);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("fails with helpful message when manifest is missing", async () => {
    // Re-import to swap the gitClone behavior for this test only.
    const gitMod = await import("../../../src/packages/git.js");
    const original = gitMod.gitClone as unknown as ReturnType<typeof vi.fn>;
    original.mockImplementationOnce(async (_url: string, _ref: string, destDir: string) => {
      // Empty tree, no manifest.
      fs.writeFileSync(path.join(destDir, "README.md"), "# nope\n", "utf-8");
    });
    await expect(
      handler({ positionals: ["acme/empty-plugin@main"], values: {} }),
    ).rejects.toThrow(/missing \.claude-plugin\/plugin\.json/);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  // Sanity check that os/fs are still functional (paranoid re: mock spillover).
  it("still has working tmpdir", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "syn-test-"));
    expect(fs.existsSync(dir)).toBe(true);
    fs.rmSync(dir, { recursive: true, force: true });
  });

  describe("local registry short-circuit (#726)", () => {
    const handler = claudePluginGroup.getCommand("install")!.handler;

    async function installOnce(): Promise<void> {
      mockFetch.mockResolvedValueOnce(
        jsonResponse(
          {
            name: "fixture-plugin",
            version: "v9",
            sha256: "f".repeat(64),
          },
          201,
        ),
      );
      await handler({ positionals: ["acme/fixture-plugin@v9"], values: {} });
    }

    it("skips git work when (name, version) is already in the local registry", async () => {
      await installOnce();
      mockFetch.mockClear();
      const gitMod = await import("../../../src/packages/git.js");
      const cloneSpy = gitMod.gitClone as unknown as ReturnType<typeof vi.fn>;
      cloneSpy.mockClear();

      // Second install with the same ref should be a no-op.
      await handler({ positionals: ["acme/fixture-plugin@v9"], values: {} });
      expect(cloneSpy).not.toHaveBeenCalled();
      expect(mockFetch).not.toHaveBeenCalled();
      const out = (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls
        .map((c: unknown[]) => String(c[0]))
        .join("");
      expect(out).toMatch(/already installed/i);
    });

    it("--force re-runs the install even when registry has the entry", async () => {
      await installOnce();
      mockFetch.mockClear();
      mockFetch.mockResolvedValueOnce(
        jsonResponse(
          {
            name: "fixture-plugin",
            version: "v9",
            sha256: "e".repeat(64),
          },
          201,
        ),
      );
      await handler({
        positionals: ["acme/fixture-plugin@v9"],
        values: { force: true },
      });
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
  });

  describe("marketplace repo (#763)", () => {
    const handler = claudePluginGroup.getCommand("install")!.handler;

    async function setupMarketplaceClone(): Promise<void> {
      const gitMod = await import("../../../src/packages/git.js");
      const clone = gitMod.gitClone as unknown as ReturnType<typeof vi.fn>;
      clone.mockImplementationOnce(async (_url: string, _ref: string, destDir: string) => {
        const cpDir = path.join(destDir, ".claude-plugin");
        fs.mkdirSync(cpDir, { recursive: true });
        fs.writeFileSync(
          path.join(cpDir, "marketplace.json"),
          JSON.stringify({
            name: "agentic-primitives",
            plugins: [
              { name: "sdlc", source: "./plugins/sdlc", category: "dev" },
              { name: "research", source: "./plugins/research", category: "dev" },
            ],
          }),
          "utf-8",
        );
        const sdlcDir = path.join(destDir, "plugins", "sdlc", ".claude-plugin");
        fs.mkdirSync(sdlcDir, { recursive: true });
        fs.writeFileSync(
          path.join(sdlcDir, "plugin.json"),
          JSON.stringify({ name: "sdlc", version: "1.0.0" }),
          "utf-8",
        );
        fs.writeFileSync(
          path.join(destDir, "plugins", "sdlc", "README.md"),
          "# sdlc\n",
          "utf-8",
        );
      });
    }

    it("errors with the available plugin list when --plugin is omitted", async () => {
      await setupMarketplaceClone();
      await expect(
        handler({ positionals: ["AgentParadise/agentic-primitives@v1"], values: {} }),
      ).rejects.toThrow(/marketplace with 2 plugins[\s\S]*sdlc[\s\S]*research/);
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("registers the picked plugin's subdir when --plugin is given", async () => {
      await setupMarketplaceClone();
      mockFetch.mockResolvedValueOnce(
        jsonResponse(
          {
            name: "sdlc",
            version: "v1",
            sha256: "1".repeat(64),
          },
          201,
        ),
      );
      await handler({
        positionals: ["AgentParadise/agentic-primitives@v1"],
        values: { plugin: "sdlc" },
      });
      expect(mockFetch).toHaveBeenCalledTimes(1);
      const req = mockFetch.mock.calls[0]![0] as Request;
      const body = JSON.parse(await req.text()) as {
        name: string;
        files: { rel_path: string }[];
      };
      expect(body.name).toBe("sdlc");
      // Files should be from the sdlc subdir, not the marketplace root.
      const rels = body.files.map((f) => f.rel_path).sort();
      expect(rels).toEqual([".claude-plugin/plugin.json", "README.md"]);
    });

    it("errors when --plugin names a plugin not in the marketplace", async () => {
      await setupMarketplaceClone();
      await expect(
        handler({
          positionals: ["AgentParadise/agentic-primitives@v1"],
          values: { plugin: "ghost" },
        }),
      ).rejects.toThrow(/Plugin 'ghost' not found.*sdlc, research/);
    });
  });
});
