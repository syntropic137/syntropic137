/**
 * The resolved definition must carry EVERY key the workflow YAML declared.
 *
 * WHY this exists: install used to project the parsed YAML into a narrow JSON
 * body, silently dropping every key that projection did not name - skills and
 * claude_plugins among them. Install now uploads the resolved definition to
 * /workflows/from-yaml instead, so the server sees the whole document. These
 * tests pin that the projection is gone and cannot quietly come back.
 */
import { describe, expect, it, beforeEach, afterEach } from "vitest";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { resolvePackage } from "../../src/packages/resolver.js";

let pkg: string;

beforeEach(() => {
  pkg = fs.mkdtempSync(path.join(os.tmpdir(), "resolvedef-"));
  fs.mkdirSync(path.join(pkg, "workflows", "demo"), { recursive: true });
});
afterEach(() => {
  fs.rmSync(pkg, { recursive: true, force: true });
});

function writeWorkflow(body: string): void {
  fs.writeFileSync(path.join(pkg, "workflows", "demo", "workflow.yaml"), body);
}

describe("resolvePackage definition", () => {
  it("keeps workflow-scope skills that the old JSON projection dropped", () => {
    writeWorkflow(`
id: demo
name: Demo
type: research
skills:
  - anthropics/skills/alpha@v1.0.0
phases:
  - id: one
    name: One
    order: 1
`);
    const { workflows } = resolvePackage(pkg);
    const def = workflows[0]!.definition;

    expect(def["skills"]).toEqual(["anthropics/skills/alpha@v1.0.0"]);
  });

  it("keeps phase-scope skills", () => {
    writeWorkflow(`
id: demo
name: Demo
type: research
phases:
  - id: one
    name: One
    order: 1
    skills:
      - anthropics/skills/beta@v2.0.0
`);
    const { workflows } = resolvePackage(pkg);
    const def = workflows[0]!.definition;
    const phases = def["phases"] as Record<string, unknown>[];

    expect(phases[0]!["skills"]).toEqual(["anthropics/skills/beta@v2.0.0"]);
  });

  it("carries prompt_file resolution into the definition, not just the projection", () => {
    fs.writeFileSync(path.join(pkg, "workflows", "demo", "one.md"), "Do the thing.\n");
    writeWorkflow(`
id: demo
name: Demo
type: research
phases:
  - id: one
    name: One
    order: 1
    prompt_file: one.md
`);
    const { workflows } = resolvePackage(pkg);
    const phases = workflows[0]!.definition["phases"] as Record<string, unknown>[];

    // WHY it must be resolved here: the server has no base_dir and rejects an
    // unresolved prompt_file, so uploading the original bytes would break
    // every plugin that uses one.
    expect(phases[0]!["prompt_template"]).toContain("Do the thing.");
    expect(phases[0]!["prompt_file"]).toBeUndefined();
  });

  it("preserves unknown top-level keys so the next new field is not dropped too", () => {
    writeWorkflow(`
id: demo
name: Demo
type: research
claude_plugins:
  - acme/plugins@v1.0.0
phases:
  - id: one
    name: One
    order: 1
`);
    const { workflows } = resolvePackage(pkg);

    expect(workflows[0]!.definition["claude_plugins"]).toEqual(["acme/plugins@v1.0.0"]);
  });
});
