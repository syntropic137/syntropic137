/**
 * `install --prune` and `update --prune` as commands (issue #1588).
 *
 * prune.test.ts covers which workflows a prune may archive. These drive the
 * install and update handlers end to end against a mocked server, for the
 * three things only the commands decide: when the flags are checked relative
 * to the upsert, what is recorded locally when the prune throws, and whether
 * an unchanged source still gets pruned.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { InstallationRecord, ResolvedWorkflow } from "../../../src/packages/models.js";

const KEPT = { id: "kept-wf", name: "Kept" };
const DROPPED = { id: "dropped-wf", name: "Dropped" };
const SHA = "abc123";

const recordInstallation = vi.fn();
const resolvePackage = vi.fn();
let installed: InstallationRecord[] = [];

vi.mock("../../../src/packages/resolver.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../src/packages/resolver.js")>()),
  loadInstalled: () => ({ version: 1, installations: installed }),
  recordInstallation: (opts: unknown) => recordInstallation(opts),
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

import { installCommand } from "../../../src/commands/workflow/install.js";
import { updateCommand } from "../../../src/commands/workflow/update.js";
import { CLIError } from "../../../src/framework/errors.js";

const mockFetch = vi.fn();
const originalStdinTTY = process.stdin.isTTY;
const originalStdoutTTY = process.stdout.isTTY;

function setTTY(value: boolean): void {
  Object.defineProperty(process.stdin, "isTTY", { value, configurable: true });
  Object.defineProperty(process.stdout, "isTTY", { value, configurable: true });
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

/** The previous install: both workflows, from SHA, so `update` sees it as current. */
function priorInstall(): InstallationRecord {
  return {
    package_name: "pkg",
    package_version: "1.0.0",
    source: "./pkg",
    source_ref: "main",
    installed_at: "2026-10-01T00:00:00Z",
    format: "single",
    workflows: [KEPT, DROPPED],
    marketplace_source: "org/marketplace",
    git_sha: SHA,
  };
}

/** Server: upserts succeed unchanged; every GET attributes the workflow to `pkg`. */
function server(getFails = false): void {
  // The typed client passes a Request; the YAML upload passes (url, init).
  mockFetch.mockImplementation(async (input: Request | string, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input.url);
    const method = typeof input === "string" ? (init?.method ?? "GET") : input.method;
    if (method === "POST") {
      return Response.json({ id: KEPT.id, name: KEPT.name, status: "unchanged", warnings: [] }, { status: 200 });
    }
    if (method === "DELETE") return new Response(null, { status: 204 });
    if (getFails) throw new TypeError("fetch failed");
    const id = decodeURIComponent(url.pathname.split("/").pop()!);
    return Response.json({ id, name: id, workflow_type: "custom", classification: "standard", package_name: "pkg" });
  });
}

function methods(): string[] {
  return mockFetch.mock.calls.map(([input, init]) =>
    typeof input === "string" ? ((init as RequestInit | undefined)?.method ?? "GET") : (input as Request).method,
  );
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
  setTTY(false);
  installed = [priorInstall()];
  resolvePackage.mockReturnValue({ manifest: { name: "pkg", version: "1.0.0" }, workflows: [workflow(KEPT)] });
});

afterEach(() => {
  vi.restoreAllMocks();
  mockFetch.mockReset();
  recordInstallation.mockReset();
  resolvePackage.mockReset();
  vi.unstubAllGlobals();
  Object.defineProperty(process.stdin, "isTTY", { value: originalStdinTTY, configurable: true });
  Object.defineProperty(process.stdout, "isTTY", { value: originalStdoutTTY, configurable: true });
});

describe("install --prune", () => {
  it("refuses --prune without --yes on a non-TTY before upserting anything", async () => {
    server();
    await expect(
      installCommand.handler({ positionals: ["./pkg"], values: { prune: true } }),
    ).rejects.toBeInstanceOf(CLIError);
    expect(methods()).toEqual([]);
    expect(recordInstallation).not.toHaveBeenCalled();
  });

  it("records the upsert that happened when the prune throws, keeping dropped workflows tracked", async () => {
    server(true);
    await expect(
      installCommand.handler({ positionals: ["./pkg"], values: { prune: true, yes: true } }),
    ).rejects.toThrow();
    expect(methods()).toContain("POST");
    expect(recordInstallation).toHaveBeenCalledTimes(1);
    expect(recordInstallation.mock.calls[0]![0].workflows).toEqual([KEPT, DROPPED]);
  });
});

describe("update --prune", () => {
  it("archives dropped workflows even when the source sha has not moved", async () => {
    server();
    await updateCommand.handler({ positionals: ["pkg"], values: { prune: true, yes: true } });
    expect(deletes()).toEqual([DROPPED.id]);
    expect(recordInstallation.mock.calls[0]![0].workflows).toEqual([KEPT]);
  });

  it("without --prune an unchanged source still short-circuits", async () => {
    server();
    await updateCommand.handler({ positionals: ["pkg"], values: {} });
    expect(methods()).toEqual([]);
  });

  it("refuses --prune without --yes on a non-TTY before upserting anything", async () => {
    server();
    await expect(
      updateCommand.handler({ positionals: ["pkg"], values: { prune: true, force: true } }),
    ).rejects.toBeInstanceOf(CLIError);
    expect(methods()).toEqual([]);
  });
});
