/**
 * `resolveSource` is what actually turns a user-typed install argument into
 * either a git clone or a local package path. The defect lived one hop
 * upstream, in `parseSource`'s local/shorthand discrimination - so a test
 * that only calls `parseSource` would not catch a regression where
 * `resolveSource` itself grew a second, independent path/shorthand check
 * that disagreed with it. This asserts the consumer: no network/git call
 * happens for a mis-shaped source, and the failure names what the user
 * actually typed, not a fabricated GitHub URL.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { resolveSource } from "../../../src/commands/workflow/install.js";

const gitClone = vi.hoisted(() => vi.fn());
const gitHeadSha = vi.hoisted(() => vi.fn(() => Promise.resolve("deadbeef")));
const makeTempDir = vi.hoisted(() => vi.fn(() => "/tmp/syn-pkg-test"));

vi.mock("../../../src/packages/git.js", () => ({
  gitClone,
  gitHeadSha,
  makeTempDir,
  removeTempDir: vi.fn(),
}));

afterEach(() => {
  vi.restoreAllMocks();
  gitClone.mockReset();
  gitHeadSha.mockReset();
  gitHeadSha.mockResolvedValue("deadbeef");
  makeTempDir.mockReset();
  makeTempDir.mockReturnValue("/tmp/syn-pkg-test");
});

describe("resolveSource", () => {
  it("never attempts a git clone for a 3-segment path, and reports the path the user typed", async () => {
    await expect(resolveSource("foo/bar/baz", "main")).rejects.toThrow(
      /foo\/bar\/baz/,
    );
    expect(gitClone).not.toHaveBeenCalled();
  });

  it("does not fabricate a github.com URL in the error for a mis-shaped path", async () => {
    await expect(resolveSource("some/nested/dir/deep", "main")).rejects.not.toThrow(
      /github\.com/,
    );
    expect(gitClone).not.toHaveBeenCalled();
  });

  it("still resolves genuine 2-segment shorthand as remote", async () => {
    // A real fixture directory, not the fake nonexistent tmpdir path: this
    // asserts resolveSource actually succeeds end to end for a genuine
    // owner/repo, rather than only that gitClone was called (a mocked clone
    // that writes nothing would otherwise let resolvePackage fail right
    // after, silently proving nothing past dispatch).
    const fixtureDir = fs.mkdtempSync(
      path.join(os.tmpdir(), "syn-resolve-source-fixture-"),
    );
    fs.writeFileSync(
      path.join(fixtureDir, "workflow.yaml"),
      "id: fixture\nname: Fixture\nphases: []\n",
      "utf-8",
    );
    try {
      gitClone.mockResolvedValue(undefined);
      makeTempDir.mockReturnValue(fixtureDir);

      const result = await resolveSource("syntropic137/workflow-library", "main");

      expect(gitClone).toHaveBeenCalledWith(
        "https://github.com/syntropic137/workflow-library.git",
        "main",
        fixtureDir,
      );
      expect(result.packagePath).toBe(fixtureDir);
      expect(result.tmpdir).toBe(fixtureDir);
      expect(result.gitSha).toBe("deadbeef");
      expect(result.workflows).toHaveLength(1);
      expect(result.workflows[0]!.id).toBe("fixture");
    } finally {
      fs.rmSync(fixtureDir, { recursive: true, force: true });
    }
  });

  // Consumer-level pins for every fabrication/misclassification shape the
  // review (#1066) reproduced against the shipped code, mirroring
  // tests/packages/resolver.test.ts but asserting what actually consumes
  // parseSource's output: whether resolveSource dispatches a git clone at
  // all, and against what URL.

  it("never attempts a git clone for a Windows drive-absolute path", async () => {
    await expect(resolveSource("C:/repo", "main")).rejects.toThrow(/C:\/repo/);
    expect(gitClone).not.toHaveBeenCalled();
  });

  it("never attempts a git clone for owner/.", async () => {
    await expect(resolveSource("foo/.", "main")).rejects.not.toThrow(/github\.com/);
    expect(gitClone).not.toHaveBeenCalled();
  });

  it("never attempts a git clone for owner/..", async () => {
    await expect(resolveSource("foo/..", "main")).rejects.not.toThrow(/github\.com/);
    expect(gitClone).not.toHaveBeenCalled();
  });

  it("never attempts a git clone for a # fragment shorthand", async () => {
    await expect(resolveSource("org/repo#v1", "main")).rejects.not.toThrow(
      /github\.com/,
    );
    expect(gitClone).not.toHaveBeenCalled();
  });

  it("never attempts a git clone for a ? query-string shorthand", async () => {
    await expect(resolveSource("org/repo?x=y", "main")).rejects.not.toThrow(
      /github\.com/,
    );
    expect(gitClone).not.toHaveBeenCalled();
  });

  it("never attempts a git clone for whitespace-padded segments", async () => {
    await expect(resolveSource(" a/b ", "main")).rejects.not.toThrow(/github\.com/);
    expect(gitClone).not.toHaveBeenCalled();
  });

  it("never attempts a git clone for a trailing slash (empty repo segment)", async () => {
    await expect(resolveSource("foo/", "main")).rejects.not.toThrow(/github\.com/);
    expect(gitClone).not.toHaveBeenCalled();
  });
});
