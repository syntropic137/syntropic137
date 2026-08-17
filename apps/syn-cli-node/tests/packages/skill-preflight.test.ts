import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  collectSkillRefs,
  pinBundledRefsInDefinition,
  runSkillPreflight,
} from "../../src/packages/skill-preflight.js";
import type { ResolvedWorkflow } from "../../src/packages/models.js";

let pkg: string;
const mockFetch = vi.fn();

beforeEach(() => {
  pkg = fs.mkdtempSync(path.join(os.tmpdir(), "skillpre-"));
  vi.stubGlobal("fetch", mockFetch);
  vi.spyOn(process.stdout, "write").mockReturnValue(true);
});
afterEach(() => {
  fs.rmSync(pkg, { recursive: true, force: true });
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  mockFetch.mockReset();
});

function workflow(definition: Record<string, unknown>): ResolvedWorkflow {
  return {
    definition,
    id: "demo",
    name: "Demo",
    workflow_type: "research",
    classification: "simple",
    repository_url: "",
    repository_ref: "main",
    description: null,
    project_name: null,
    requires_repos: false,
    phases: [],
    input_declarations: [],
    source_path: pkg,
  };
}

function writeBundledSkill(name: string, body = "# skill"): void {
  const dir = path.join(pkg, "skills", name);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(
    path.join(dir, "SKILL.md"),
    `---\nname: ${name}\ndescription: Use when relevant.\n---\n\n${body}\n`,
  );
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("collectSkillRefs", () => {
  it("collects refs from BOTH workflow scope and phase scope", () => {
    const refs = collectSkillRefs([
      workflow({
        id: "review",
        skills: ["anthropics/skills/alpha@v1.0.0"],
        phases: [{ id: "one", skills: ["anthropics/skills/beta@v2.0.0"] }],
      }),
    ]);

    expect(refs.map((r) => r.skillName).sort()).toEqual(["alpha", "beta"]);
  });

  it("returns nothing for a plugin that declares no skills", () => {
    expect(collectSkillRefs([workflow({ id: "review", phases: [{ id: "one" }] })])).toEqual([]);
  });

  it("resolves a bundled ref to a path inside the plugin", () => {
    const refs = collectSkillRefs([
      workflow({ id: "review", skills: ["./skills/repo-conventions"] }),
    ]);

    expect(refs).toEqual([
      { kind: "bundled", skillName: "repo-conventions", localPath: "./skills/repo-conventions" },
    ]);
  });

  it("fails the whole preflight on an unpinned ref, before any API call", () => {
    expect(() =>
      collectSkillRefs([workflow({ id: "review", skills: ["anthropics/skills/alpha@latest"] })]),
    ).toThrow(/latest/i);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("dedupes a skill declared at both scopes", () => {
    const refs = collectSkillRefs([
      workflow({
        id: "review",
        skills: ["anthropics/skills/alpha@v1.0.0"],
        phases: [{ id: "one", skills: ["anthropics/skills/alpha@v1.0.0"] }],
      }),
    ]);

    expect(refs).toHaveLength(1);
  });
});

describe("pinBundledRefsInDefinition", () => {
  it("rewrites a bundled path into a pinned, content-addressed ref", () => {
    writeBundledSkill("repo-conventions");
    const wf = workflow({ id: "review", skills: ["./skills/repo-conventions"] });

    pinBundledRefsInDefinition(wf.definition, pkg);

    const skills = wf.definition["skills"] as Record<string, unknown>[];
    expect(skills[0]!["source"]).toBe("./skills/repo-conventions");
    expect(skills[0]!["name"]).toBe("repo-conventions");
    expect(String(skills[0]!["version"])).toMatch(/^sha256-[0-9a-f]{64}$/);
  });

  it("rewrites phase-scope refs too, not just workflow scope", () => {
    writeBundledSkill("repo-conventions");
    const wf = workflow({
      id: "review",
      phases: [{ id: "one", skills: ["./skills/repo-conventions"] }],
    });

    pinBundledRefsInDefinition(wf.definition, pkg);

    const phases = wf.definition["phases"] as Record<string, unknown>[];
    const skills = phases[0]!["skills"] as Record<string, unknown>[];
    expect(String(skills[0]!["version"])).toMatch(/^sha256-/);
  });

  it("gives an edited bundled skill a different pinned version", () => {
    writeBundledSkill("repo-conventions", "# first");
    const first = workflow({ id: "r", skills: ["./skills/repo-conventions"] });
    pinBundledRefsInDefinition(first.definition, pkg);

    writeBundledSkill("repo-conventions", "# second");
    const second = workflow({ id: "r", skills: ["./skills/repo-conventions"] });
    pinBundledRefsInDefinition(second.definition, pkg);

    const v1 = (first.definition["skills"] as Record<string, unknown>[])[0]!["version"];
    const v2 = (second.definition["skills"] as Record<string, unknown>[])[0]!["version"];
    expect(v1).not.toBe(v2);
  });

  it("fails when a bundled skill directory is missing, naming the path", () => {
    const wf = workflow({ id: "review", skills: ["./skills/nope"] });

    expect(() => pinBundledRefsInDefinition(wf.definition, pkg)).toThrow(/nope/);
  });

  it("leaves an already-pinned external ref semantically unchanged", () => {
    const wf = workflow({ id: "review", skills: ["anthropics/skills/alpha@v1.0.0"] });

    pinBundledRefsInDefinition(wf.definition, pkg);

    const skills = wf.definition["skills"] as Record<string, unknown>[];
    expect(skills[0]).toEqual({
      source: "https://github.com/anthropics/skills",
      version: "v1.0.0",
      name: "alpha",
    });
  });
});

describe("runSkillPreflight", () => {
  it("uploads a bundled skill that is not yet registered", async () => {
    writeBundledSkill("repo-conventions");
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ registered: false }))
      .mockResolvedValueOnce(jsonResponse({ skill_name: "repo-conventions" }, 201));

    const result = await runSkillPreflight(pkg, [
      workflow({ id: "review", skills: ["./skills/repo-conventions"] }),
    ]);

    expect(result.registered).toHaveLength(1);
    expect(result.skipped).toHaveLength(0);
    const postArg = mockFetch.mock.calls[1]![0];
    const postUrl = postArg instanceof Request ? postArg.url : String(postArg);
    expect(postUrl).toContain("/skills/registrations");
  });

  it("performs NO upload when the content hash is already registered", async () => {
    writeBundledSkill("repo-conventions");
    mockFetch.mockResolvedValue(jsonResponse({ registered: true, resolved_sha: "sha256-x" }));

    const result = await runSkillPreflight(pkg, [
      workflow({ id: "review", skills: ["./skills/repo-conventions"] }),
    ]);

    // This IS the caching claim: one lookup, zero uploads.
    expect(result.skipped).toHaveLength(1);
    expect(result.registered).toHaveLength(0);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("does nothing at all when no skills are declared", async () => {
    const result = await runSkillPreflight(pkg, [workflow({ id: "review", phases: [] })]);

    expect(result).toEqual({ registered: [], skipped: [] });
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
