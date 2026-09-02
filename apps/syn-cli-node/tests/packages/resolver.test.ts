import { describe, it, expect, afterEach } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  parseSource,
  resolvePackage,
} from "../../src/packages/resolver.js";

describe("parseSource", () => {
  it("detects HTTPS URLs as remote", () => {
    const result = parseSource("https://github.com/org/repo.git");
    expect(result).toEqual({ resolved: "https://github.com/org/repo.git", isRemote: true });
  });

  it("detects SSH URLs as remote", () => {
    const result = parseSource("git@github.com:org/repo.git");
    expect(result).toEqual({ resolved: "git@github.com:org/repo.git", isRemote: true });
  });

  it("detects GitHub shorthand as remote", () => {
    const result = parseSource("syntropic137/workflow-library");
    expect(result).toEqual({
      resolved: "https://github.com/syntropic137/workflow-library.git",
      isRemote: true,
    });
  });

  it("detects relative paths as local", () => {
    const result = parseSource("./my-package");
    expect(result).toEqual({ resolved: "./my-package", isRemote: false });
  });

  it("detects absolute paths as local", () => {
    const result = parseSource("/tmp/my-package");
    expect(result).toEqual({ resolved: "/tmp/my-package", isRemote: false });
  });

  it("treats bare names as local", () => {
    const result = parseSource("my-workflow");
    expect(result).toEqual({ resolved: "my-workflow", isRemote: false });
  });
});

function makeTmpDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), "syn-test-requires-repos-"));
}

function cleanup(dir: string): void {
  fs.rmSync(dir, { recursive: true, force: true });
}

describe("requires_repos inference (ADR-058)", () => {
  let tmpDir: string;

  afterEach(() => {
    if (tmpDir) cleanup(tmpDir);
  });

  describe("resolveStandaloneYaml (via resolvePackage)", () => {
    // #1050: this used to assert `false` here (inferred from the absent
    // `repository` field), while the Python server's
    // `infer_requires_repos` asserted `true` for the identical unset case
    // (test_yaml_to_command.py::test_default_true_when_no_repository_and_no_explicit_value).
    // Both were green - that contradiction was the bug. Default is opt-out
    // (True) on both sides now.
    it("defaults to true when requires_repos is absent, agreeing with the server's infer_requires_repos (standalone has no repository field)", () => {
      tmpDir = makeTmpDir();
      fs.writeFileSync(
        path.join(tmpDir, "my-workflow.yaml"),
        "id: standalone\nname: Standalone\nphases: []\n",
        "utf-8",
      );
      const { workflows } = resolvePackage(tmpDir);
      expect(workflows).toHaveLength(1);
      expect(workflows[0]!.requires_repos).toBe(true);
    });

    it("returns true when requires_repos: true is explicit in standalone YAML", () => {
      tmpDir = makeTmpDir();
      fs.writeFileSync(
        path.join(tmpDir, "my-workflow.yaml"),
        "id: standalone\nname: Standalone\nrequires_repos: true\nphases: []\n",
        "utf-8",
      );
      const { workflows } = resolvePackage(tmpDir);
      expect(workflows).toHaveLength(1);
      expect(workflows[0]!.requires_repos).toBe(true);
    });

    it("returns false when requires_repos: false is explicit in standalone YAML", () => {
      tmpDir = makeTmpDir();
      fs.writeFileSync(
        path.join(tmpDir, "my-workflow.yaml"),
        "id: standalone\nname: Standalone\nrequires_repos: false\nphases: []\n",
        "utf-8",
      );
      const { workflows } = resolvePackage(tmpDir);
      expect(workflows).toHaveLength(1);
      expect(workflows[0]!.requires_repos).toBe(false);
    });
  });
});
