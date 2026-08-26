import { execFile } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

function runGit(args: string[], cwd?: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = execFile(
      "git",
      args,
      { timeout: 120_000, cwd },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error(`git ${args[0]} failed: ${stderr.trim()}`));
        } else {
          // Resolves stdout so callers that need output (gitHeadSha) can read
          // it; callers that only care about success ignore the value.
          resolve(typeof stdout === "string" ? stdout : String(stdout));
        }
      },
    );
    child.unref?.();
  });
}

/**
 * Shallow-clone `url` at `ref` into `destDir`.
 *
 * `ref` may be a branch, a tag, or a full commit SHA. `git clone --branch`
 * resolves only named refs, so a SHA pin - which skill refs explicitly
 * document as valid, and which is the most reproducible pin available - would
 * otherwise fail with "Remote branch not found". The named-ref path is tried
 * first because it is one round trip; the fetch-by-object-id path runs only
 * when that fails, so existing branch and tag behaviour is unchanged.
 */
export async function gitClone(url: string, ref: string, destDir: string): Promise<void> {
  try {
    await runGit(["clone", "--depth=1", "--branch", ref, url, destDir]);
    return;
  } catch (namedRefError) {
    try {
      fs.mkdirSync(destDir, { recursive: true });
      await runGit(["init", "--quiet"], destDir);
      await runGit(["remote", "add", "origin", url], destDir);
      await runGit(["fetch", "--depth=1", "--quiet", "origin", ref], destDir);
      await runGit(["checkout", "--quiet", "FETCH_HEAD"], destDir);
    } catch {
      // Report the named-ref failure: it is the common case and its message
      // ("Remote branch X not found") is the more actionable of the two.
      throw namedRefError;
    }
  }
}

/**
 * Resolve the commit actually checked out in a completed clone.
 *
 * WHY this rather than `git ls-remote` (issue #822): provenance must describe
 * the bytes we installed. Asking the remote for the ref's sha is a separate
 * round trip, so if the ref moves between the clone and the query we record
 * commit B while having installed commit A. A digest that can describe
 * different content than what was installed is worse than no digest, because
 * every downstream check then trusts it.
 *
 * Returns null when the sha cannot be read, so callers omit the digest rather
 * than sending something unverified.
 */
export async function gitHeadSha(repoDir: string): Promise<string | null> {
  try {
    const sha = await runGit(["rev-parse", "HEAD"], repoDir);
    const trimmed = sha.trim();
    return trimmed.length > 0 ? trimmed : null;
  } catch {
    return null;
  }
}

export function gitLsRemote(
  repo: string,
  ref: string,
): Promise<string | null> {
  return new Promise((resolve) => {
    execFile(
      "git",
      ["ls-remote", `https://github.com/${repo}.git`, ref],
      { timeout: 30_000 },
      (error, stdout) => {
        if (error) {
          resolve(null);
          return;
        }
        const line = stdout.trim().split("\n")[0] ?? "";
        if (line.includes("\t")) {
          resolve(line.split("\t")[0]!);
        } else {
          resolve(null);
        }
      },
    );
  });
}

export function makeTempDir(prefix: string): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

export function removeTempDir(dir: string): void {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    // Ignore cleanup errors
  }
}
