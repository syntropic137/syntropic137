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
import { resolvePackage } from "../../src/packages/resolver.js";
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
