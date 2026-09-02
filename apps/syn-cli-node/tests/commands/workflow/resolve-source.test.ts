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
import { resolveSource } from "../../../src/commands/workflow/install.js";

const gitClone = vi.hoisted(() => vi.fn());

vi.mock("../../../src/packages/git.js", () => ({
  gitClone,
  gitHeadSha: vi.fn(),
  makeTempDir: vi.fn(() => "/tmp/syn-pkg-test"),
  removeTempDir: vi.fn(),
}));

afterEach(() => {
  vi.restoreAllMocks();
  gitClone.mockReset();
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
    gitClone.mockResolvedValue(undefined);
    // resolveFromGit also needs a package to load once "cloned"; point it at
    // a real fixture directory instead of the fake tmpdir so resolvePackage
    // succeeds after the (mocked) clone.
    // We only assert that a clone was attempted with the expected URL.
    await resolveSource("syntropic137/workflow-library", "main").catch(() => {
      // resolvePackage against the fake tmpdir will fail after the clone;
      // that's fine, we only care that a clone was attempted.
    });
    expect(gitClone).toHaveBeenCalledWith(
      "https://github.com/syntropic137/workflow-library.git",
      "main",
      "/tmp/syn-pkg-test",
    );
  });
});
