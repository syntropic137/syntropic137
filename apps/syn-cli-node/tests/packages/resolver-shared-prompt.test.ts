/**
 * `shared://<name>` phase prompts, resolved against `phase-library/`.
 *
 * WHY: the server has no base directory and rejects any `prompt_file` still
 * present in an uploaded document, so a `shared://` reference the CLI does not
 * inline turns into a 400 at install time. The multi-workflow package format
 * documents `shared://` as THE way to reuse a phase, which made every plugin
 * using it uninstallable.
 */
import { describe, expect, it, beforeEach, afterEach } from "vitest";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import { resolvePackage } from "../../src/packages/resolver.js";

let pkg: string;

beforeEach(() => {
  pkg = fs.mkdtempSync(path.join(os.tmpdir(), "sharedprompt-"));
  fs.mkdirSync(path.join(pkg, "workflows", "demo"), { recursive: true });
  fs.mkdirSync(path.join(pkg, "phase-library"), { recursive: true });
  fs.writeFileSync(
    path.join(pkg, "syntropic137-plugin.json"),
    JSON.stringify({ manifest_version: 1, name: "demo", version: "0.1.0" }),
  );
});
afterEach(() => {
  fs.rmSync(pkg, { recursive: true, force: true });
});

function writeWorkflow(promptFile: string): void {
  fs.writeFileSync(
    path.join(pkg, "workflows", "demo", "workflow.yaml"),
    `id: demo\nname: Demo\ntype: research\nphases:\n  - id: one\n    name: One\n    order: 1\n    prompt_file: ${promptFile}\n`,
  );
}

describe("shared:// prompt resolution", () => {
  it("inlines phase-library/<name>.md and drops prompt_file", () => {
    fs.writeFileSync(path.join(pkg, "phase-library", "summarize.md"), "Summarize the work.\n");
    writeWorkflow("shared://summarize");

    const { workflows } = resolvePackage(pkg);
    const phase = workflows[0]!.phases[0]!;

    expect(phase["prompt_file"]).toBeUndefined();
    expect(phase["prompt_template"]).toContain("Summarize the work.");
  });

  it("applies frontmatter from the shared phase file", () => {
    fs.writeFileSync(
      path.join(pkg, "phase-library", "summarize.md"),
      "---\nmodel: haiku\nargument-hint: \"[topic]\"\n---\n\nSummarize.\n",
    );
    writeWorkflow("shared://summarize");

    const phase = resolvePackage(pkg).workflows[0]!.phases[0]!;
    expect(phase["model"]).toBe("haiku");
    expect(phase["argument_hint"]).toBe("[topic]");
  });

  it("fails loudly when the shared phase does not exist", () => {
    writeWorkflow("shared://missing");
    // Silently leaving prompt_file in place produced an opaque server 400.
    expect(() => resolvePackage(pkg)).toThrow(/shared:\/\/ reference 'shared:\/\/missing'/);
  });

  it("rejects a reference that escapes the phase library", () => {
    writeWorkflow("shared://../../etc/passwd");
    expect(() => resolvePackage(pkg)).toThrow(/escapes the phase-library directory/);
  });

  it("rejects an empty reference", () => {
    writeWorkflow('"shared://"');
    expect(() => resolvePackage(pkg)).toThrow(/shared:\/\/ reference is empty/);
  });
});
