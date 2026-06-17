import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  findInstalled,
  listInstalled,
  loadInstalled,
  recordInstallation,
  registryPath,
  removeInstalled,
  saveInstalled,
} from "../../src/packages/claude-plugin-registry.js";

describe("claude-plugin-registry", () => {
  beforeEach(() => {
    // Clean slate per test by removing the file (registryPath is fixed
    // because synPath was captured at module load).
    const p = registryPath();
    if (fs.existsSync(p)) fs.rmSync(p);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    const p = registryPath();
    if (fs.existsSync(p)) fs.rmSync(p);
  });

  it("returns empty registry when file is missing", () => {
    const reg = loadInstalled();
    expect(reg.entries).toEqual([]);
  });

  it("round-trips save/load", () => {
    saveInstalled({
      entries: [
        {
          name: "foo",
          version: "1.0.0",
          source_url: "https://github.com/acme/foo",
          resolved_sha: "abc",
          installed_at: "2026-05-04T00:00:00Z",
          marketplace_source: null,
        },
      ],
    });
    const reg = loadInstalled();
    expect(reg.entries).toHaveLength(1);
    expect(reg.entries[0]!.name).toBe("foo");
  });

  it("warns and returns empty for corrupt registry", () => {
    fs.mkdirSync(path.dirname(registryPath()), { recursive: true });
    fs.writeFileSync(registryPath(), "{not json", "utf-8");
    const reg = loadInstalled();
    expect(reg.entries).toEqual([]);
    const stderr = (process.stderr.write as ReturnType<typeof vi.fn>).mock.calls
      .map((c: unknown[]) => String(c[0]))
      .join("");
    expect(stderr).toMatch(/corrupt/i);
  });

  it("recordInstallation upserts on (name, version)", () => {
    recordInstallation({
      name: "foo",
      version: "1.0.0",
      source_url: "u1",
      resolved_sha: "sha1",
    });
    recordInstallation({
      name: "foo",
      version: "1.0.0",
      source_url: "u2",
      resolved_sha: "sha2",
    });
    const all = listInstalled();
    expect(all).toHaveLength(1);
    expect(all[0]!.resolved_sha).toBe("sha2");
    expect(all[0]!.source_url).toBe("u2");
  });

  it("findInstalled returns null for unknown (name, version)", () => {
    recordInstallation({
      name: "foo",
      version: "1.0.0",
      source_url: "u",
      resolved_sha: "s",
    });
    expect(findInstalled("foo", "2.0.0")).toBeNull();
    expect(findInstalled("bar", "1.0.0")).toBeNull();
    expect(findInstalled("foo", "1.0.0")?.name).toBe("foo");
  });

  it("removeInstalled returns false for missing entries", () => {
    expect(removeInstalled("nope", "1")).toBe(false);
    recordInstallation({
      name: "foo",
      version: "1.0.0",
      source_url: "u",
      resolved_sha: "s",
    });
    expect(removeInstalled("foo", "1.0.0")).toBe(true);
    expect(findInstalled("foo", "1.0.0")).toBeNull();
  });

  it("listInstalled is sorted by (name, version)", () => {
    recordInstallation({
      name: "zeta",
      version: "1.0.0",
      source_url: "u",
      resolved_sha: "s",
    });
    recordInstallation({
      name: "alpha",
      version: "2.0.0",
      source_url: "u",
      resolved_sha: "s",
    });
    recordInstallation({
      name: "alpha",
      version: "1.0.0",
      source_url: "u",
      resolved_sha: "s",
    });
    const names = listInstalled().map((e) => `${e.name}@${e.version}`);
    expect(names).toEqual(["alpha@1.0.0", "alpha@2.0.0", "zeta@1.0.0"]);
  });

  it("saveInstalled writes atomically (no .tmp- file remains)", () => {
    saveInstalled({
      entries: [
        {
          name: "x",
          version: "1",
          source_url: "u",
          resolved_sha: "s",
          installed_at: "2026-05-04T00:00:00Z",
          marketplace_source: null,
        },
      ],
    });
    const dir = path.dirname(registryPath());
    const stragglers = fs
      .readdirSync(dir)
      .filter((f) => f.includes(".tmp-"));
    expect(stragglers).toEqual([]);
  });
});
