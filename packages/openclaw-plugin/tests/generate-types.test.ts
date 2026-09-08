/**
 * The drift gate has to actually fail. #1182 was not "the types were wrong" --
 * it was "nothing would have told us", so a check that exits 0 whatever it
 * finds would reproduce the bug while looking like the fix.
 *
 * These run the real script against the real committed file and the real
 * spec, because the paths are the part most likely to rot.
 */

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const script = path.join(packageRoot, "scripts", "generate-types.ts");
const generated = path.join(packageRoot, "src", "generated", "api-types.ts");

const pristine = fs.readFileSync(generated, "utf-8");
afterEach(() => fs.writeFileSync(generated, pristine, "utf-8"));

/** Exit code of `generate-types.ts --check`, whatever it is. */
function checkExitCode(): number {
  try {
    execFileSync("npx", ["tsx", script, "--check"], { cwd: packageRoot, stdio: "pipe" });
    return 0;
  } catch (err) {
    return (err as { status?: number }).status ?? -1;
  }
}

describe("generate-types --check", () => {
  it("passes against the committed types", () => {
    expect(checkExitCode()).toBe(0);
  });

  it("fails when the committed types no longer match the spec", () => {
    // A field REMOVED, which is the drift that hurts: the plugin goes on
    // reading something the server stopped promising.
    fs.writeFileSync(generated, pristine.replace("            status_counts", "            _gone"), "utf-8");
    expect(checkExitCode()).toBe(1);
  });

  it("fails when the committed types are missing entirely", () => {
    // Not "skip, nothing to compare". A fresh clone that never ran codegen is
    // exactly the state the gate exists to catch.
    fs.rmSync(generated);
    expect(checkExitCode()).toBe(1);
  });
});
