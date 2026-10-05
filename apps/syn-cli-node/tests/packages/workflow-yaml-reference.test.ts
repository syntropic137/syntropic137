/**
 * The CLI's half of the workflow YAML contract (#1618).
 *
 * `tests/fixtures/workflow-yaml-reference.json` is what PyYAML - the server's
 * parser - reads from every workflow YAML under workflows/, written by
 * scripts/workflow_yaml_reference.py and kept current by a Python test. Here
 * the CLI's loader must read the same thing. The minimal parser this replaced
 * read sdlc/implement-v3 as 4 phases instead of 10 and nothing failed.
 */
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { installWorkflowsViaApi } from "../../src/commands/workflow/install.js";
import { detectFormat, resolvePackage } from "../../src/packages/resolver.js";
import type { ResolvedWorkflow } from "../../src/packages/models.js";
import { parseYaml } from "../../src/packages/yaml.js";

const REPO_ROOT = path.resolve(import.meta.dirname, "../../../..");

interface PhaseReference {
  id: string | null;
  order: number | null;
  model: string | null;
  prompt_file: string | null;
}

interface Reference {
  files: Record<string, { phases: PhaseReference[]; document_sha256: string }>;
}

const reference = JSON.parse(
  fs.readFileSync(path.join(import.meta.dirname, "../fixtures/workflow-yaml-reference.json"), "utf-8"),
) as Reference;

/** Must match `canonical_json` in scripts/workflow_yaml_reference.py. */
function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.keys(value)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonicalJson((value as Record<string, unknown>)[k])}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value);
}

function pick<T>(value: unknown, kind: "string" | "number"): T | null {
  return typeof value === kind ? (value as T) : null;
}

function phasesOf(document: unknown): PhaseReference[] {
  const phases = (document as { phases?: unknown } | null)?.phases;
  if (!Array.isArray(phases)) return [];
  return phases
    .filter((p): p is Record<string, unknown> => p !== null && typeof p === "object" && !Array.isArray(p))
    .map((p) => ({
      id: pick<string>(p["id"], "string"),
      order: pick<number>(p["order"], "number"),
      model: pick<string>(p["model"], "string"),
      prompt_file: pick<string>(p["prompt_file"], "string"),
    }));
}

function workflowYamlFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return workflowYamlFiles(full);
    return /\.ya?ml$/.test(entry.name) ? [path.relative(REPO_ROOT, full).split(path.sep).join("/")] : [];
  });
}

describe("CLI YAML loader agrees with the PyYAML reference", () => {
  it("covers exactly the workflow YAMLs in the repo", () => {
    expect(workflowYamlFiles(path.join(REPO_ROOT, "workflows")).sort()).toEqual(
      Object.keys(reference.files).sort(),
    );
  });

  it.each(Object.keys(reference.files))("%s", (rel) => {
    const document = parseYaml(fs.readFileSync(path.join(REPO_ROOT, rel), "utf-8"), rel);
    const expected = reference.files[rel]!;
    expect(phasesOf(document)).toEqual(expected.phases);
    expect(createHash("sha256").update(canonicalJson(document), "utf-8").digest("hex")).toBe(
      expected.document_sha256,
    );
  });

  it("reads implement-v3's merge keys as ten phases", () => {
    const rel = "workflows/sdlc/implement-v3/workflow.yaml";
    const document = parseYaml(fs.readFileSync(path.join(REPO_ROOT, rel), "utf-8"), rel);
    expect(phasesOf(document).map((p) => p.id)).toEqual([
      "premise", "implement", "verify",
      "fix", "reverify", "fix_2", "reverify_2", "fix_3", "reverify_3",
      "finalize_pr",
    ]);
  });
});

const UPLOAD_FIXTURE = path.join(import.meta.dirname, "../fixtures/workflow-upload-bodies.json");

/**
 * The directory `syn workflow install` is pointed at to install `rel`: the
 * nearest plugin root above it, else the directory holding it.
 */
function installRootOf(rel: string): string {
  const workflowsDir = path.join(REPO_ROOT, "workflows");
  for (let dir = path.dirname(path.join(REPO_ROOT, rel)); dir.startsWith(workflowsDir); dir = path.dirname(dir)) {
    if (fs.existsSync(path.join(dir, "syntropic137-plugin.json"))) return dir;
  }
  return path.dirname(path.join(REPO_ROOT, rel));
}

/** The YAML files `resolvePackage(root)` reads, in the order it returns them. */
function yamlsResolvedFrom(root: string): string[] {
  const format = detectFormat(root);
  if (format === "single") return [path.join(root, "workflow.yaml")];
  if (format === "multi") {
    const dir = path.join(root, "workflows");
    return fs
      .readdirSync(dir)
      .sort()
      .map((d) => path.join(dir, d, "workflow.yaml"))
      .filter((f) => fs.existsSync(f));
  }
  return fs
    .readdirSync(root)
    .filter((f) => f.endsWith(".yaml") || f.endsWith(".yml"))
    .sort()
    .map((f) => path.join(root, f));
}

/** Every phase-bearing workflow YAML, as the CLI's loader resolves it for upload. */
function uploadBodies(): Record<string, Record<string, unknown>> {
  const wanted = new Set(Object.keys(reference.files).filter((rel) => reference.files[rel]!.phases.length > 0));
  const bodies: Record<string, Record<string, unknown>> = {};
  for (const root of new Set([...wanted].map(installRootOf))) {
    const files = yamlsResolvedFrom(root);
    const { workflows } = resolvePackage(root);
    expect(workflows.map((w: ResolvedWorkflow) => w.id)).toHaveLength(files.length);
    files.forEach((file, i) => {
      const rel = path.relative(REPO_ROOT, file).split(path.sep).join("/");
      if (wanted.has(rel)) bodies[rel] = workflows[i]!.definition;
    });
  }
  expect(Object.keys(bodies).sort()).toEqual([...wanted].sort());
  return bodies;
}

describe("CLI package loader agrees with the PyYAML reference", () => {
  // `parseYaml` agreeing is not enough: install uploads what `resolvePackage`
  // makes of the file, after prompt files are inlined and frontmatter merged.
  const bodies = uploadBodies();

  it.each(Object.keys(bodies))("%s", (rel) => {
    const expected = reference.files[rel]!.phases;
    const resolved = phasesOf(bodies[rel]);
    expect(resolved.map(({ id, order }) => ({ id, order }))).toEqual(
      expected.map(({ id, order }) => ({ id, order })),
    );
    // An explicit YAML model wins over frontmatter, so it must survive as is.
    resolved.forEach((phase, i) => {
      if (expected[i]!.model !== null) expect(phase.model).toBe(expected[i]!.model);
      expect(phase.prompt_file).toBeNull();
    });
  });

  it("matches the committed upload bodies the server-side test stores", () => {
    // scripts/tests/test_workflow_yaml_reference.py posts each of these to the
    // from-yaml service and checks the stored phases. Regenerate with
    // UPDATE_UPLOAD_FIXTURE=1 pnpm exec vitest run tests/packages/workflow-yaml-reference.test.ts
    const rendered = `${JSON.stringify(bodies, null, 2)}\n`;
    if (process.env["UPDATE_UPLOAD_FIXTURE"] === "1") fs.writeFileSync(UPLOAD_FIXTURE, rendered);
    expect(fs.readFileSync(UPLOAD_FIXTURE, "utf-8")).toBe(rendered);
  });
});

describe("implement-v3 install upload", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  // The hop after the parser: what `syn workflow install` actually POSTs.
  // The Python half pins that the server stores every phase of such a body.
  it("uploads all ten phases, in order, to /workflows/from-yaml", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "x", name: "x", status: "created" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(process.stdout, "write").mockReturnValue(true);

    const { workflows } = resolvePackage(path.join(REPO_ROOT, "workflows/sdlc/implement-v3"));
    await installWorkflowsViaApi(workflows);

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(String(fetchMock.mock.calls[0]![0])).toContain("/workflows/from-yaml");
    const uploaded = JSON.parse(Buffer.from(init.body as Uint8Array).toString("utf-8")) as unknown;
    const expected = reference.files["workflows/sdlc/implement-v3/workflow.yaml"]!.phases;
    expect(phasesOf(uploaded).map(({ id, order, model }) => ({ id, order, model }))).toEqual(
      expected.map(({ id, order, model }) => ({ id, order, model })),
    );
  });
});
