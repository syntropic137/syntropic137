/**
 * `gitClone` must accept a commit SHA, not only a named ref.
 *
 * Skill refs document "tag, branch, or commit sha" as valid pins, and a SHA is
 * the most reproducible of the three. `git clone --branch` resolves only named
 * refs, so a SHA pin used to fail with "Remote branch not found".
 */
import { describe, expect, it, beforeEach, afterEach } from "vitest";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { gitClone } from "../../src/packages/git.js";

let origin: string;
let dest: string;

function git(args: string[], cwd: string): string {
  return execFileSync("git", args, {
    cwd,
    encoding: "utf-8",
    env: { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@e", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@e" },
  }).trim();
}

beforeEach(() => {
  origin = fs.mkdtempSync(path.join(os.tmpdir(), "gitorigin-"));
  dest = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "gitdest-")), "clone");
  git(["init", "--quiet", "-b", "main"], origin);
  // Allow fetching an arbitrary object id from this local "server".
  git(["config", "uploadpack.allowAnySHA1InWant", "true"], origin);
  fs.writeFileSync(path.join(origin, "SKILL.md"), "# pinned");
  git(["add", "."], origin);
  git(["commit", "--quiet", "-m", "initial"], origin);
});

afterEach(() => {
  fs.rmSync(origin, { recursive: true, force: true });
  fs.rmSync(path.dirname(dest), { recursive: true, force: true });
});

describe("gitClone", () => {
  it("clones a branch", async () => {
    await gitClone(origin, "main", dest);
    expect(fs.readFileSync(path.join(dest, "SKILL.md"), "utf-8")).toBe("# pinned");
  });

  it("clones a tag", async () => {
    git(["tag", "v1.0.0"], origin);
    await gitClone(origin, "v1.0.0", dest);
    expect(fs.readFileSync(path.join(dest, "SKILL.md"), "utf-8")).toBe("# pinned");
  });

  it("clones an untagged commit SHA", async () => {
    const sha = git(["rev-parse", "HEAD"], origin);
    await gitClone(origin, sha, dest);
    expect(fs.readFileSync(path.join(dest, "SKILL.md"), "utf-8")).toBe("# pinned");
  });

  it("reports the named-ref error for a ref that does not exist at all", async () => {
    await expect(gitClone(origin, "v9.9.9", dest)).rejects.toThrow(/not found|clone failed/i);
  });
});
