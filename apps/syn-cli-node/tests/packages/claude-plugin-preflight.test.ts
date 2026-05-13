import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mock git so the preflight register flow doesn't actually clone.
vi.mock("../../src/packages/git.js", async () => {
  const realFs = await import("node:fs");
  const realOs = await import("node:os");
  const realPath = await import("node:path");
  return {
    gitClone: vi.fn(async (_url: string, _ref: string, destDir: string) => {
      const pluginDir = realPath.join(destDir, ".claude-plugin");
      realFs.mkdirSync(pluginDir, { recursive: true });
      realFs.writeFileSync(
        realPath.join(pluginDir, "plugin.json"),
        JSON.stringify({ name: "preflight-fixture" }),
      );
    }),
    gitLsRemote: vi.fn(async () => null),
    makeTempDir: (prefix: string) =>
      realFs.mkdtempSync(realPath.join(realOs.tmpdir(), prefix)),
    removeTempDir: (dir: string) =>
      realFs.rmSync(dir, { recursive: true, force: true }),
  };
});

import { runClaudePluginPreflight } from "../../src/packages/claude-plugin-preflight.js";

describe("runClaudePluginPreflight", () => {
  let tmp: string;
  const mockFetch = vi.fn();

  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "syn-pref-"));
    vi.stubGlobal("fetch", mockFetch);
    vi.spyOn(process.stdout, "write").mockReturnValue(true);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  function jsonResponse(data: unknown, status = 200): Response {
    return new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  it("returns null when no claude_plugins declared", async () => {
    fs.writeFileSync(
      path.join(tmp, "workflow.yaml"),
      "id: foo\nname: foo\nphases: []\n",
      "utf-8",
    );
    const r = await runClaudePluginPreflight(tmp);
    expect(r).toBeNull();
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("fires register POST for missing plugin and skips one in lock", async () => {
    fs.writeFileSync(
      path.join(tmp, "workflow.yaml"),
      [
        "id: foo",
        "name: foo",
        "claude_plugins:",
        "  - acme/already@v1",
        "  - acme/missing@v2",
        "phases: []",
        "",
      ].join("\n"),
      "utf-8",
    );

    // Sequence:
    //   GET /claude-plugins/already/v1 -> 200 (in lock)
    //   GET /claude-plugins/missing/v2 -> 404 (not in lock)
    //   POST /claude-plugins/registrations -> 201
    mockFetch
      .mockResolvedValueOnce(
        jsonResponse({
          name: "already",
          source_url: "https://github.com/acme/already",
          version: "v1",
          resolved_sha: "x",
          tree_storage_prefix: "p/",
          registered_at: "2026-05-05T00:00:00Z",
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ detail: "not found" }, 404))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            name: "preflight-fixture",
            version: "v2",
            sha256: "abcd".repeat(16),
          },
          201,
        ),
      );

    const r = await runClaudePluginPreflight(tmp);
    expect(r).not.toBeNull();
    expect(r!.registered.map((p) => p.name)).toEqual(["missing"]);
    expect(r!.skipped.map((p) => p.name)).toEqual(["already"]);

    expect(mockFetch).toHaveBeenCalledTimes(3);
    const lastReq = mockFetch.mock.calls[2]![0] as Request;
    expect(lastReq.url).toContain("/claude-plugins/registrations");
  });

  it("aborts the whole pre-flight if a register call fails", async () => {
    fs.writeFileSync(
      path.join(tmp, "workflow.yaml"),
      [
        "id: foo",
        "name: foo",
        "claude_plugins:",
        "  - acme/missing@v2",
        "phases: []",
        "",
      ].join("\n"),
      "utf-8",
    );

    mockFetch
      .mockResolvedValueOnce(jsonResponse({ detail: "not found" }, 404))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "boom" }, 500),
      );

    await expect(runClaudePluginPreflight(tmp)).rejects.toThrow(
      /pre-flight failed.*missing.*No workflows were installed/s,
    );
  });
});
