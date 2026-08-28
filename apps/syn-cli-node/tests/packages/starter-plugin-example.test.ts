/**
 * The committed starter-plugin example is a fixture, not decoration.
 *
 * WHY this exists: `workflows/examples/starter-plugin/` is the artifact a
 * plugin author copies. Before this test nothing executed it, and it had been
 * uninstallable for as long as `shared://` went unresolved in the CLI. These
 * assertions pin the two things an author copies it for: that it resolves at
 * all, and that it demonstrates BOTH skill sources with per-phase divergence.
 */
import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import { resolvePackage } from "../../src/packages/resolver.js";
import { collectSkillRefs, pinBundledRefsInDefinition } from "../../src/packages/skill-preflight.js";
import type { ResolvedWorkflow } from "../../src/packages/models.js";

const STARTER = fileURLToPath(
  new URL("../../../../workflows/examples/starter-plugin", import.meta.url),
);

function byId(workflows: readonly ResolvedWorkflow[], id: string): ResolvedWorkflow {
  const found = workflows.find((w) => w.id === id);
  if (!found) throw new Error(`workflow ${id} not found in example package`);
  return found;
}

function phaseSkillNames(workflow: ResolvedWorkflow, phaseId: string): string[] {
  const phase = workflow.phases.find((p) => p["id"] === phaseId);
  if (!phase) throw new Error(`phase ${phaseId} not found`);
  const skills = phase["skills"];
  return Array.isArray(skills) ? skills.map((s) => String(s)) : [];
}

describe("starter-plugin example", () => {
  it("resolves every phase prompt, including shared:// references", () => {
    const { workflows } = resolvePackage(STARTER);

    expect(workflows.map((w) => w.id).sort()).toEqual([
      "starter-pr-review-v1",
      "starter-research-v1",
    ]);

    for (const workflow of workflows) {
      for (const phase of workflow.phases) {
        // An unresolved prompt_file is what the server rejects with
        // "prompt_file 'shared://summarize' was not resolved".
        expect(phase["prompt_file"]).toBeUndefined();
        expect(String(phase["prompt_template"] ?? "")).not.toBe("");
      }
    }
  });

  it("keeps every phase on the haiku model so validation runs stay cheap", () => {
    const { workflows } = resolvePackage(STARTER);
    for (const workflow of workflows) {
      for (const phase of workflow.phases) {
        expect(phase["model"]).toBe("haiku");
      }
    }
  });

  it("declares both a vendored and an external skill", () => {
    const { workflows } = resolvePackage(STARTER);
    const refs = collectSkillRefs(workflows);

    const bundled = refs.filter((r) => r.kind === "bundled");
    const external = refs.filter((r) => r.kind === "external");

    expect(bundled.map((r) => r.skillName)).toEqual(["repo-conventions"]);
    expect(external).toHaveLength(1);
    expect(external[0]).toMatchObject({
      skillName: "doc-coauthoring",
      sourceUrl: "https://github.com/anthropics/skills",
    });
    // Pinned to an immutable ref. '@latest' is rejected by the parser, but a
    // branch name would parse fine and quietly un-pin the example.
    expect(external[0]?.version).toMatch(/^[0-9a-f]{40}$/);
  });

  it("ships the vendored skill it declares", () => {
    expect(fs.existsSync(path.join(STARTER, "skills", "repo-conventions", "SKILL.md"))).toBe(true);
  });

  it("gives different phases different skills", () => {
    const { workflows } = resolvePackage(STARTER);
    const research = byId(workflows, "starter-research-v1");
    const prReview = byId(workflows, "starter-pr-review-v1");

    // Workflow scope covers every phase in the research workflow; the
    // investigate phase adds one more on top.
    expect(research.definition["skills"]).toEqual(["./skills/repo-conventions"]);
    expect(phaseSkillNames(research, "investigate")).toHaveLength(1);
    expect(phaseSkillNames(research, "summarize")).toHaveLength(0);

    // The pr-review workflow declares nothing at workflow scope, so its
    // summarize phase runs with no skills at all.
    expect(prReview.definition["skills"]).toBeUndefined();
    expect(phaseSkillNames(prReview, "review")).toEqual(["./skills/repo-conventions"]);
    expect(phaseSkillNames(prReview, "summarize")).toHaveLength(0);
  });

  it("pins the vendored skill by content hash before upload", () => {
    const { workflows } = resolvePackage(STARTER);
    const prReview = byId(workflows, "starter-pr-review-v1");

    pinBundledRefsInDefinition(prReview.definition, STARTER);

    const phases = prReview.definition["phases"] as Record<string, unknown>[];
    const review = phases.find((p) => p["id"] === "review");
    const skills = review?.["skills"] as Record<string, unknown>[];

    expect(skills).toHaveLength(1);
    expect(skills[0]?.["name"]).toBe("repo-conventions");
    expect(skills[0]?.["source"]).toBe("./skills/repo-conventions");
    expect(String(skills[0]?.["version"])).toMatch(/^sha256-[0-9a-f]{64}$/);
  });
});
