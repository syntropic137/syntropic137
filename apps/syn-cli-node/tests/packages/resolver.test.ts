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

describe("requires_repos is the server's verdict, not the CLI's (#1050)", () => {
  // The CLI used to infer this itself: absent `requires_repos` plus no
  // `repository:` block meant `false`, while the server's
  // `infer_requires_repos` calls the same YAML `true`. Nothing read the CLI's
  // answer, so the two rules disagreed silently for as long as they coexisted.
  // The CLI now states no verdict at all - it uploads the declaration and the
  // server decides - so these assert the CLI stays out of it.
  let tmpDir: string;

  afterEach(() => {
    if (tmpDir) cleanup(tmpDir);
  });

  function resolveYaml(yaml: string): Record<string, unknown> {
    tmpDir = makeTmpDir();
    fs.writeFileSync(path.join(tmpDir, "my-workflow.yaml"), yaml, "utf-8");
    const { workflows } = resolvePackage(tmpDir);
    expect(workflows).toHaveLength(1);
    // Read through a Record so this keeps compiling - and keeps failing - if
    // the field is ever put back on ResolvedWorkflow.
    return workflows[0]! as unknown as Record<string, unknown>;
  }

  it("answers nothing for a YAML that declares neither requires_repos nor repository", () => {
    // The exact document from #1050: the CLI answered `false` here, the server
    // answers `true`, and the author was told their workflow needed no repo
    // right up until execution refused it.
    const resolved = resolveYaml("id: standalone\nname: Standalone\nphases: []\n");

    expect(resolved["requires_repos"]).toBeUndefined();
  });

  it("answers nothing even when the YAML declares it explicitly", () => {
    // Copying the declaration up would be harmless today and wrong the moment
    // the server's rule gains a case the copy does not have.
    const resolved = resolveYaml(
      "id: standalone\nname: Standalone\nrequires_repos: true\nphases: []\n",
    );

    expect(resolved["requires_repos"]).toBeUndefined();
  });

  it.each([
    ["absent", "id: standalone\nname: Standalone\nphases: []\n", undefined],
    ["true", "id: standalone\nname: Standalone\nrequires_repos: true\nphases: []\n", true],
    ["false", "id: standalone\nname: Standalone\nrequires_repos: false\nphases: []\n", false],
  ])(
    "uploads the declaration verbatim when it is %s, so the server can apply its rule",
    (_label, yaml, declared) => {
      // `definition` is the body install POSTs to /workflows/from-yaml. An
      // absent field must arrive absent: injecting a default here would decide
      // the question on the server's behalf and reintroduce the second rule by
      // the back door.
      const definition = resolveYaml(yaml)["definition"] as Record<string, unknown>;

      expect(definition["requires_repos"]).toBe(declared);
    },
  );
});
