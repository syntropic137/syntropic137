import { execFile } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export function gitClone(
  url: string,
  ref: string,
  destDir: string,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = execFile(
      "git",
      ["clone", "--depth=1", "--branch", ref, url, destDir],
      { timeout: 120_000 },
      (error, _stdout, stderr) => {
        if (error) {
          reject(new Error(`git clone failed: ${stderr.trim()}`));
        } else {
          resolve();
        }
      },
    );
    child.unref?.();
  });
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
