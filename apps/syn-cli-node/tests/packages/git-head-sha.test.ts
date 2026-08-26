/**
 * Provenance must describe the bytes we installed (issue #822).
 *
 * The digest used to come from a separate `git ls-remote` after the clone.
 * If the ref moved between the two, the recorded sha described commit B
 * while commit A was on disk, and every downstream check then trusted it.
 * A digest that can describe different content than what was installed is
 * worse than no digest.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import { gitHeadSha } from "../../src/packages/git.js";

function makeRepo(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "syn-headsha-"));
  const git = (...args: string[]) => execFileSync("git", args, { cwd: dir, stdio: "pipe" });
  git("init", "--quiet");
  git("config", "user.email", "test@example.com");
  git("config", "user.name", "Test");
  fs.writeFileSync(path.join(dir, "a.txt"), "one");
  git("add", ".");
  git("commit", "--quiet", "-m", "first");
  return dir;
}

describe("gitHeadSha", () => {
  it("returns the commit actually checked out", async () => {
    const dir = makeRepo();
    try {
      const expected = execFileSync("git", ["rev-parse", "HEAD"], { cwd: dir })
        .toString()
        .trim();

      await expect(gitHeadSha(dir)).resolves.toBe(expected);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  it("tracks the working tree rather than a remote ref", async () => {
    const dir = makeRepo();
    try {
      const first = await gitHeadSha(dir);
      execFileSync("git", ["config", "user.email", "t@e.com"], { cwd: dir });
      fs.writeFileSync(path.join(dir, "a.txt"), "two");
      execFileSync("git", ["add", "."], { cwd: dir });
      execFileSync("git", ["commit", "--quiet", "-m", "second"], { cwd: dir });

      const second = await gitHeadSha(dir);
      expect(second).not.toBe(first);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  it("returns null rather than an unverified value when it cannot read a sha", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "syn-notrepo-"));
    try {
      await expect(gitHeadSha(dir)).resolves.toBeNull();
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
