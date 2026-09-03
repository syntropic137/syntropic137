import { describe, it, expect, afterEach } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  isGitHubShorthand,
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

  it("does not treat a 3-segment path as GitHub owner/repo shorthand", () => {
    // A GitHub repo identity is always exactly owner/repo. "foo/bar/baz" has
    // no such identity, so parseSource must not fabricate
    // https://github.com/foo/bar/baz.git out of it.
    const result = parseSource("foo/bar/baz");
    expect(result.isRemote).toBe(false);
    expect(result.resolved).not.toContain("github.com");
  });

  it("does not treat a deeply nested path as GitHub owner/repo shorthand", () => {
    const result = parseSource("some/nested/dir/deep");
    expect(result.isRemote).toBe(false);
    expect(result.resolved).not.toContain("github.com");
  });

  it("treats a tilde-prefixed path as local, not shorthand", () => {
    const result = parseSource("~/local/workflow");
    expect(result.isRemote).toBe(false);
    expect(result.resolved).not.toContain("github.com");
  });

  it("expands a bare ~ to the home directory", () => {
    // Not merely "not remote" (that would pass even unexpanded, as it did
    // before this fix) - the resolved path must actually be the home
    // directory, since nothing outside a shell expands `~` and this string
    // is what downstream code calls path.resolve() on.
    const result = parseSource("~");
    expect(result).toEqual({ resolved: os.homedir(), isRemote: false });
  });

  it("expands ~/... to a path under the home directory", () => {
    const result = parseSource("~/a/b");
    expect(result).toEqual({
      resolved: path.join(os.homedir(), "a", "b"),
      isRemote: false,
    });
  });

  // Every case below reproduces an input the review (#1066) showed fabricates
  // a github.com URL or misclassifies against the shipped segment-count
  // check: a segment COUNT is not a validation of GitHub repository
  // identity. Each asserts both that the input is not remote and that no
  // github.com URL was fabricated from it, since "not remote" alone would
  // also be true of a fabricated *local* misreading.

  it("does not treat a Windows drive-absolute path as GitHub shorthand", () => {
    // Two slash-separated segments, same as owner/repo - but ":" is not a
    // valid character in a GitHub owner name.
    const result = parseSource("C:/repo");
    expect(result.isRemote).toBe(false);
    expect(result.resolved).not.toContain("github.com");
  });

  it("does not treat owner/. as GitHub shorthand", () => {
    const result = parseSource("foo/.");
    expect(result.isRemote).toBe(false);
    expect(result.resolved).not.toContain("github.com");
  });

  it("does not treat owner/.. as GitHub shorthand", () => {
    const result = parseSource("foo/..");
    expect(result.isRemote).toBe(false);
    expect(result.resolved).not.toContain("github.com");
  });

  it("does not treat a # fragment as part of a valid repo name", () => {
    const result = parseSource("org/repo#v1");
    expect(result.isRemote).toBe(false);
    expect(result.resolved).not.toContain("github.com");
  });

  it("does not treat a ? query string as part of a valid repo name", () => {
    const result = parseSource("org/repo?x=y");
    expect(result.isRemote).toBe(false);
    expect(result.resolved).not.toContain("github.com");
  });

  it("does not treat whitespace-padded segments as GitHub shorthand", () => {
    const result = parseSource(" a/b ");
    expect(result.isRemote).toBe(false);
    expect(result.resolved).not.toContain("github.com");
  });

  it("does not treat a trailing slash (empty repo segment) as GitHub shorthand", () => {
    // Regression pin for the coverage hole the review found: mutating the
    // non-empty-segment guard away left this case fabricating
    // https://github.com/foo/.git with all 15 original tests still green.
    const result = parseSource("foo/");
    expect(result.isRemote).toBe(false);
    expect(result.resolved).not.toContain("github.com");
  });

  it("does not treat an empty middle segment as GitHub shorthand", () => {
    const result = parseSource("foo//bar");
    expect(result.isRemote).toBe(false);
    expect(result.resolved).not.toContain("github.com");
  });

  it("still treats genuine owner/repo as GitHub shorthand", () => {
    const result = parseSource("torvalds/linux");
    expect(result).toEqual({
      resolved: "https://github.com/torvalds/linux.git",
      isRemote: true,
    });
  });

  it("rejects an owner with consecutive hyphens", () => {
    // GitHub's own join-page validation: no two hyphens in a row.
    const result = parseSource("fo--o/repo");
    expect(result.isRemote).toBe(false);
    expect(result.resolved).not.toContain("github.com");
  });

  it("rejects an owner that starts with a hyphen", () => {
    const result = parseSource("-foo/repo");
    expect(result.isRemote).toBe(false);
    expect(result.resolved).not.toContain("github.com");
  });

  it("an existing two-segment directory is local, not shorthand", () => {
    // Pins the intended contract the review flagged as accidental: an
    // existing local directory wins over the shorthand reading, even when
    // its name is shaped exactly like owner/repo.
    const dir = makeTmpDir();
    const nestedRepo = path.join(dir, "owner", "repo");
    fs.mkdirSync(nestedRepo, { recursive: true });
    const cwd = process.cwd();
    process.chdir(dir);
    try {
      const result = parseSource("owner/repo");
      expect(result).toEqual({ resolved: "owner/repo", isRemote: false });
    } finally {
      process.chdir(cwd);
      cleanup(dir);
    }
  });
});

// GitHub owner/repo grammar invariant (issue #1066, second review round).
//
// The character-class fix (isValidGitHubOwner/isValidGitHubRepoName) is
// correct today, but every existing test only pins the fabrication-shape
// REGRESSIONS (colons, `#`/`?`, `.`/`..`, whitespace, trailing slash). None
// of them assert the grammar's own BOUNDARIES: a one-character owner, the
// 39/40-character owner cutoff, uppercase, or a repo containing `.`/`_`, or
// the 100/101-character repo cutoff. A mutation that shrinks either cap, or
// narrows a character class, leaves every one of those tests green while
// rejecting a real, valid GitHub identity - a worse failure than the bug
// this PR fixes, because it is silent (nothing turns red) and user-facing
// (a legitimate `owner/repo` install just stops working).
//
// Each case below is named for the specific boundary it pins, so a mutation
// that violates it fails a specific, legible test rather than merely
// dropping a pass count.
describe("GitHub owner/repo grammar invariant (issue #1066 second review)", () => {
  const validOwner = "a";
  const validRepo = "a";

  describe("owner boundaries", () => {
    it.each<{ name: string; owner: string; accept: boolean }>([
      { name: "accepts a 1-character owner (the shortest legal owner)", owner: "a", accept: true },
      { name: "accepts a 39-character owner (GitHub's own maximum)", owner: "a".repeat(39), accept: true },
      { name: "rejects a 40-character owner (one past GitHub's maximum)", owner: "a".repeat(40), accept: false },
      { name: "accepts an uppercase owner", owner: "ABC", accept: true },
      { name: "accepts a mixed-case owner", owner: "Torvalds", accept: true },
      { name: "accepts digits in an owner", owner: "abc123", accept: true },
      { name: "accepts a single interior hyphen in an owner", owner: "ab-cd", accept: true },
      { name: "rejects an owner ending in a hyphen", owner: "abc-", accept: false },
      { name: "rejects an owner starting with a hyphen", owner: "-abc", accept: false },
      { name: "rejects consecutive hyphens in an owner", owner: "ab--cd", accept: false },
      { name: "rejects an underscore in an owner (not in GitHub's owner charset)", owner: "ab_cd", accept: false },
      { name: "rejects a dot in an owner (not in GitHub's owner charset)", owner: "ab.cd", accept: false },
      { name: "rejects a space in an owner", owner: "ab cd", accept: false },
      { name: "rejects an empty owner", owner: "", accept: false },
    ])("$name", ({ owner, accept }) => {
      expect(isGitHubShorthand(`${owner}/${validRepo}`)).toBe(accept);
    });
  });

  describe("repo boundaries", () => {
    it.each<{ name: string; repo: string; accept: boolean }>([
      { name: "accepts a 1-character repo (the shortest legal repo)", repo: "a", accept: true },
      { name: "accepts a 100-character repo (GitHub's own maximum)", repo: "a".repeat(100), accept: true },
      { name: "rejects a 101-character repo (one past GitHub's maximum)", repo: "a".repeat(101), accept: false },
      { name: "accepts an uppercase repo", repo: "REPO", accept: true },
      { name: "accepts a mixed-case repo", repo: "Linux", accept: true },
      { name: "accepts digits in a repo", repo: "repo123", accept: true },
      { name: "accepts a dot in a repo (explicitly allowed by GitHub's own docs)", repo: "my.repo", accept: true },
      { name: "accepts an underscore in a repo (explicitly allowed by GitHub's own docs)", repo: "my_repo", accept: true },
      { name: "accepts a hyphen in a repo", repo: "my-repo", accept: true },
      { name: "rejects a colon in a repo", repo: "repo:tag", accept: false },
      { name: "rejects a # in a repo", repo: "repo#v1", accept: false },
      { name: "rejects a ? in a repo", repo: "repo?x=y", accept: false },
      { name: "rejects a space in a repo", repo: "my repo", accept: false },
      { name: "rejects an empty repo", repo: "", accept: false },
    ])("$name", ({ repo, accept }) => {
      expect(isGitHubShorthand(`${validOwner}/${repo}`)).toBe(accept);
    });
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
    it("defaults to false when requires_repos is absent (standalone has no repository field)", () => {
      tmpDir = makeTmpDir();
      fs.writeFileSync(
        path.join(tmpDir, "my-workflow.yaml"),
        "id: standalone\nname: Standalone\nphases: []\n",
        "utf-8",
      );
      const { workflows } = resolvePackage(tmpDir);
      expect(workflows).toHaveLength(1);
      expect(workflows[0]!.requires_repos).toBe(false);
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
