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

  it("reports an escape, not a missing file, for a traversal to nowhere", () => {
    // Covers the LEXICAL check specifically: the target does not exist, so a
    // realpath-only check would report "does not exist" and hide the escape.
    writeWorkflow("shared://../../no-such-dir-9f3a/passwd");
    expect(() => resolvePackage(pkg)).toThrow(/escapes the phase-library directory/);
  });

  it("rejects an empty reference", () => {
    writeWorkflow('"shared://"');
    expect(() => resolvePackage(pkg)).toThrow(/shared:\/\/ reference is empty/);
  });
});

/**
 * Containment must survive symlinks.
 *
 * `path.resolve` only normalizes SEGMENTS, so a lexical check accepts a link
 * that lives inside the library and points anywhere on the host. Python's
 * `Path.resolve()` follows links before checking, so the CLI was accepting
 * packages the domain rejects, and `readFileSync` then uploaded a host file as
 * `prompt_template`.
 */
describe("shared:// symlink containment", () => {
  let outside: string;

  beforeEach(() => {
    outside = fs.mkdtempSync(path.join(os.tmpdir(), "sharedprompt-outside-"));
  });
  afterEach(() => {
    fs.rmSync(outside, { recursive: true, force: true });
  });

  it("rejects a phase-library entry that symlinks outside the package", () => {
    const secret = path.join(outside, "host-file.md");
    fs.writeFileSync(secret, "TOP SECRET HOST CONTENT\n");
    fs.symlinkSync(secret, path.join(pkg, "phase-library", "secret.md"));
    writeWorkflow("shared://secret");

    expect(() => resolvePackage(pkg)).toThrow(/escapes the phase-library directory/);
  });

  it("still follows a symlink that stays inside the library", () => {
    fs.writeFileSync(path.join(pkg, "phase-library", "real.md"), "Real shared phase.\n");
    fs.symlinkSync(
      path.join(pkg, "phase-library", "real.md"),
      path.join(pkg, "phase-library", "alias.md"),
    );
    writeWorkflow("shared://alias");

    const phase = resolvePackage(pkg).workflows[0]!.phases[0]!;
    expect(phase["prompt_template"]).toContain("Real shared phase.");
  });

  it("rejects a local prompt_file that symlinks outside the workflow dir", () => {
    const secret = path.join(outside, "host-file.md");
    fs.writeFileSync(secret, "TOP SECRET HOST CONTENT\n");
    fs.symlinkSync(secret, path.join(pkg, "workflows", "demo", "leak.md"));
    writeWorkflow("leak.md");

    expect(() => resolvePackage(pkg)).toThrow(/escapes base directory/);
  });
});

/**
 * Presence/null semantics, matching `_resolve_phase_prompt_file`.
 *
 * The CLI resolves and the server validates, so truthiness on either side of
 * that seam is a divergence: the CLI would ship a document the domain would
 * have built differently, or refused outright.
 */
describe("phase prompt resolution matches the domain", () => {
  function writePhase(extraYaml: string): void {
    fs.writeFileSync(
      path.join(pkg, "workflows", "demo", "workflow.yaml"),
      `id: demo\nname: Demo\ntype: research\nphases:\n  - id: one\n    name: One\n    order: 1\n${extraYaml}`,
    );
  }

  it("rejects a phase that sets both prompt_template and prompt_file", () => {
    fs.writeFileSync(path.join(pkg, "phase-library", "summarize.md"), "Summarize.\n");
    writePhase(`    prompt_template: "inline text"\n    prompt_file: shared://summarize\n`);

    expect(() => resolvePackage(pkg)).toThrow(/not both/);
  });

  it("treats an explicitly empty prompt_template as present, not absent", () => {
    // Falsy but NOT null: the domain's `is not None` check rejects this.
    fs.writeFileSync(path.join(pkg, "phase-library", "summarize.md"), "Summarize.\n");
    writePhase(`    prompt_template: ""\n    prompt_file: shared://summarize\n`);

    expect(() => resolvePackage(pkg)).toThrow(/not both/);
  });

  it("resolves when prompt_template is explicitly null", () => {
    // `null` IS absent to the domain, so this must resolve rather than throw.
    fs.writeFileSync(path.join(pkg, "phase-library", "summarize.md"), "Summarize.\n");
    writePhase(`    prompt_template: null\n    prompt_file: shared://summarize\n`);

    const phase = resolvePackage(pkg).workflows[0]!.phases[0]!;
    expect(phase["prompt_template"]).toBe("Summarize.");
  });

  it("does not let frontmatter overwrite an explicitly falsy YAML value", () => {
    fs.writeFileSync(
      path.join(pkg, "phase-library", "summarize.md"),
      "---\nmax-tokens: 4096\n---\n\nSummarize.\n",
    );
    writePhase(`    max_tokens: 0\n    prompt_file: shared://summarize\n`);

    const phase = resolvePackage(pkg).workflows[0]!.phases[0]!;
    expect(phase["max_tokens"]).toBe(0);
  });

  it("merges a falsy frontmatter value the phase does not set", () => {
    fs.writeFileSync(
      path.join(pkg, "phase-library", "summarize.md"),
      "---\nmax-tokens: 0\ntimeout-seconds: 0\nargument-hint: \"\"\n---\n\nSummarize.\n",
    );
    writePhase(`    prompt_file: shared://summarize\n`);

    const phase = resolvePackage(pkg).workflows[0]!.phases[0]!;
    expect(phase["max_tokens"]).toBe(0);
    expect(phase["timeout_seconds"]).toBe(0);
    expect(phase["argument_hint"]).toBe("");
  });

  it("passes through frontmatter keys outside the kebab map, as the domain does", () => {
    fs.writeFileSync(
      path.join(pkg, "phase-library", "summarize.md"),
      "---\nexecution-type: parallel\ndescription: from frontmatter\n---\n\nSummarize.\n",
    );
    writePhase(`    prompt_file: shared://summarize\n`);

    const phase = resolvePackage(pkg).workflows[0]!.phases[0]!;
    expect(phase["execution_type"]).toBe("parallel");
    expect(phase["description"]).toBe("from frontmatter");
  });

  it("drops empty entries when splitting allowed-tools, as the domain does", () => {
    fs.writeFileSync(
      path.join(pkg, "phase-library", "summarize.md"),
      "---\nallowed-tools: \"Read, Glob,,\"\n---\n\nSummarize.\n",
    );
    writePhase(`    prompt_file: shared://summarize\n`);

    const phase = resolvePackage(pkg).workflows[0]!.phases[0]!;
    expect(phase["allowed_tools"]).toEqual(["Read", "Glob"]);
  });

  it("fails loudly when a local prompt_file does not exist", () => {
    // The domain raises FileNotFoundError; silently leaving prompt_file in
    // place only moved the failure to an opaque server 400.
    writePhase(`    prompt_file: missing.md\n`);
    expect(() => resolvePackage(pkg)).toThrow(/does not exist/);
  });

  it("rejects an absolute prompt_file", () => {
    writePhase(`    prompt_file: /etc/hosts\n`);
    expect(() => resolvePackage(pkg)).toThrow(/must be a relative path/);
  });
});
