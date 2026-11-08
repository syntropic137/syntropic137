/**
 * `update` and `uninstall` against a registry already holding two records for
 * one package (issue #886).
 *
 * prune-commands.test.ts replaces `loadInstalled`, so it cannot see how the
 * stored file is read. These keep the real registry and seed `installed.json`
 * the way a pre-#883 CLI left it: the older record first, each naming a
 * workflow the other does not. Before #886 both commands saw only that first
 * record, so the newer record's workflow was never archived and never
 * re-recorded, yet `uninstall` still dropped it from the registry.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { InstallationRecord, ResolvedWorkflow } from "../../../src/packages/models.js";

const KEPT = { id: "kept-wf", name: "Kept" };
const OLD_A = { id: "old-a-wf", name: "Old A" };
const OLD_B = { id: "old-b-wf", name: "Old B" };
const SHA = "abc123";

const resolvePackage = vi.fn();

vi.mock("../../../src/packages/resolver.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../src/packages/resolver.js")>()),
  resolvePackage: (p: string) => resolvePackage(p),
  detectFormat: () => "single",
}));
vi.mock("../../../src/packages/claude-plugin-preflight.js", () => ({
  runClaudePluginPreflight: async () => undefined,
}));
vi.mock("../../../src/packages/skill-preflight.js", () => ({ runSkillPreflight: async () => undefined }));
vi.mock("../../../src/marketplace/client.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../src/marketplace/client.js")>()),
  resolvePluginByName: async () => ["reg", { repo: "org/pkg" }, {}],
  getRemoteRefSha: async () => SHA,
}));

import { uninstallCommand, updateCommand } from "../../../src/commands/workflow/update.js";
import { loadInstalled, saveInstalled } from "../../../src/packages/resolver.js";

const mockFetch = vi.fn();

function stored(installedAt: string, workflows: InstallationRecord["workflows"]): InstallationRecord {
  return {
    package_name: "pkg",
    package_version: "1.0.0",
    source: "./pkg",
    source_ref: "main",
    installed_at: installedAt,
    format: "single",
    workflows,
    marketplace_source: "org/marketplace",
    git_sha: SHA,
  };
}

function workflow(ref: { id: string; name: string }): ResolvedWorkflow {
  return {
    definition: { id: ref.id, name: ref.name, phases: [] },
    id: ref.id,
    name: ref.name,
    workflow_type: "research",
    classification: "simple",
    repository_url: "",
    repository_ref: "main",
    description: null,
    project_name: null,
    requires_repos: false,
    phases: [],
    input_declarations: [],
    source_path: "/tmp/pkg",
  };
}

/** Server: upserts succeed unchanged; every GET attributes the workflow to `pkg`. */
function server(): void {
  mockFetch.mockImplementation(async (input: Request | string, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input.url);
    const method = typeof input === "string" ? (init?.method ?? "GET") : input.method;
    if (method === "POST") {
      return Response.json({ id: KEPT.id, name: KEPT.name, status: "unchanged", warnings: [] }, { status: 200 });
    }
    if (method === "DELETE") return new Response(null, { status: 204 });
    const id = decodeURIComponent(url.pathname.split("/").pop()!);
    return Response.json({ id, name: id, workflow_type: "custom", classification: "standard", package_name: "pkg" });
  });
}

function deletes(): string[] {
  return mockFetch.mock.calls
    .map((c) => c[0])
    .filter((r): r is Request => typeof r !== "string" && r.method === "DELETE")
    .map((r) => decodeURIComponent(new URL(r.url).pathname.split("/").pop()!));
}

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  vi.spyOn(process.stdout, "write").mockReturnValue(true);
  vi.spyOn(process.stderr, "write").mockReturnValue(true);
  vi.spyOn(console, "log").mockReturnValue(undefined);
  vi.spyOn(console, "error").mockReturnValue(undefined);
  saveInstalled({
    version: 1,
    installations: [
      stored("2026-10-01T00:00:00.000Z", [KEPT, OLD_A]),
      stored("2026-10-02T00:00:00.000Z", [KEPT, OLD_B]),
    ],
  });
  resolvePackage.mockReturnValue({ manifest: { name: "pkg", version: "1.0.0" }, workflows: [workflow(KEPT)], skipped: [] });
  server();
});

afterEach(() => {
  vi.restoreAllMocks();
  mockFetch.mockReset();
  resolvePackage.mockReset();
  vi.unstubAllGlobals();
});

describe("uninstall with duplicate records", () => {
  it("archives every record's workflows and leaves no entry", async () => {
    await uninstallCommand.handler({ positionals: ["pkg"], values: {} });

    expect(deletes().sort()).toEqual([KEPT.id, OLD_A.id, OLD_B.id].sort());
    expect(loadInstalled().installations).toEqual([]);
  });
});

describe("update with duplicate records", () => {
  it("--prune archives the workflows either record dropped", async () => {
    await updateCommand.handler({ positionals: ["pkg"], values: { prune: true, yes: true } });

    expect(deletes().sort()).toEqual([OLD_A.id, OLD_B.id].sort());
    expect(loadInstalled().installations.map((r) => r.workflows)).toEqual([[KEPT]]);
  });

  it("without --prune keeps every record's dropped workflows tracked", async () => {
    await updateCommand.handler({ positionals: ["pkg"], values: { force: true } });

    expect(deletes()).toEqual([]);
    const { installations } = loadInstalled();
    expect(installations).toHaveLength(1);
    expect(installations[0]!.workflows.map((w) => w.id).sort()).toEqual([KEPT.id, OLD_A.id, OLD_B.id].sort());
  });
});
