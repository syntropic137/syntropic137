import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  MAX_TREE_BYTES,
  parseClaudePluginRef,
  readPluginManifest,
  walkPluginTree,
} from "../../src/packages/claude-plugin.js";
import { CLIError } from "../../src/framework/errors.js";

describe("parseClaudePluginRef", () => {
  it("parses github shorthand", () => {
    const r = parseClaudePluginRef("acme/cool-plugin@v1.2.3");
    expect(r.name).toBe("cool-plugin");
    expect(r.source_url).toBe("https://github.com/acme/cool-plugin");
    expect(r.version).toBe("v1.2.3");
  });

  it("parses full https URL with version", () => {
    const r = parseClaudePluginRef("https://gitlab.com/acme/foo@main");
    expect(r.source_url).toBe("https://gitlab.com/acme/foo");
    expect(r.version).toBe("main");
    expect(r.name).toBe("foo");
  });

  it("strips .git suffix when computing name", () => {
    const r = parseClaudePluginRef("https://example.com/foo.git@v1");
    expect(r.name).toBe("foo");
  });

  it("normalizes bare-host shorthand to https", () => {
    const r = parseClaudePluginRef("github.com/acme/bar@v1");
    expect(r.source_url).toBe("https://github.com/acme/bar");
  });

  it("rejects empty input", () => {
    expect(() => parseClaudePluginRef("")).toThrow(CLIError);
  });

  it("rejects @latest", () => {
    expect(() => parseClaudePluginRef("acme/foo@latest")).toThrow(/latest/i);
  });

  it("rejects malformed input", () => {
    expect(() => parseClaudePluginRef("just-a-name")).toThrow(CLIError);
    expect(() => parseClaudePluginRef("acme/foo")).toThrow(CLIError);
  });

  it("rejects URL forms missing version", () => {
    expect(() => parseClaudePluginRef("https://example.com/foo")).toThrow(CLIError);
  });
});

describe("readPluginManifest + walkPluginTree", () => {
  let tmp: string;

  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "syn-cp-test-"));
  });
  afterEach(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  it("reads a valid manifest", () => {
    fs.mkdirSync(path.join(tmp, ".claude-plugin"), { recursive: true });
    fs.writeFileSync(
      path.join(tmp, ".claude-plugin", "plugin.json"),
      JSON.stringify({ name: "p1", version: "0.1.0" }),
    );
    const m = readPluginManifest(tmp);
    expect(m["name"]).toBe("p1");
  });

  it("throws when manifest missing", () => {
    expect(() => readPluginManifest(tmp)).toThrow(/missing .claude-plugin/);
  });

  it("throws when manifest has no name", () => {
    fs.mkdirSync(path.join(tmp, ".claude-plugin"), { recursive: true });
    fs.writeFileSync(path.join(tmp, ".claude-plugin", "plugin.json"), "{}");
    expect(() => readPluginManifest(tmp)).toThrow(/non-empty 'name'/);
  });

  it("walks tree, skips .git, returns sorted base64 entries", () => {
    fs.mkdirSync(path.join(tmp, ".git"), { recursive: true });
    fs.writeFileSync(path.join(tmp, ".git", "HEAD"), "should be skipped");
    fs.mkdirSync(path.join(tmp, "sub"), { recursive: true });
    fs.writeFileSync(path.join(tmp, "sub", "b.txt"), "hello");
    fs.writeFileSync(path.join(tmp, "a.txt"), "world");

    const entries = walkPluginTree(tmp);
    const paths = entries.map((e) => e.rel_path);
    expect(paths).toEqual(["a.txt", "sub/b.txt"]);
    expect(Buffer.from(entries[0]!.content_b64, "base64").toString("utf-8")).toBe(
      "world",
    );
  });

  it("aborts when tree exceeds MAX_TREE_BYTES", () => {
    // Write a single >50MiB file to trip the cap.
    const big = Buffer.alloc(MAX_TREE_BYTES + 1, "x");
    fs.writeFileSync(path.join(tmp, "huge.bin"), big);
    expect(() => walkPluginTree(tmp)).toThrow(/exceeds/i);
  });
});
