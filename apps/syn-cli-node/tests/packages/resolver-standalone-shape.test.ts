/**
 * A YAML file is a workflow only if it has phases (issue #1949).
 *
 * `syn workflow install syntropic137/syntropic137 --dry-run` resolved the repo
 * root as a standalone package and reported pnpm-lock.yaml, vsa.yaml and the
 * rest as valid 0-phase workflows. These pin the resolver rule for every
 * format, and drive `install --dry-run` itself, because the handler is what
 * printed "package is valid".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { resolvePackage } from "../../src/packages/resolver.js";
import { installCommand } from "../../src/commands/workflow/install.js";
import { CLIError } from "../../src/framework/errors.js";

const WORKFLOW = "id: real\nname: Real\nphases:\n  - id: build\n    prompt_template: go\n";
const LOCKFILE = "lockfileVersion: '9.0'\nsettings:\n  autoInstallPeers: true\n";

let dir: string;

function pkg(files: Record<string, string>): string {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "syn-standalone-shape-"));
  for (const [rel, content] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(dir, rel)), { recursive: true });
    fs.writeFileSync(path.join(dir, rel), content, "utf-8");
  }
  return dir;
}

afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
});

describe("standalone resolution", () => {
  it("keeps only the YAML that is a workflow, and reports why each other file was skipped", () => {
    const { workflows, skipped } = resolvePackage(
      pkg({
        "pnpm-lock.yaml": LOCKFILE,
        "real.yaml": WORKFLOW,
        "list.yml": "- a\n- b\n",
        "empty-phases.yaml": "id: hollow\nphases: []\n",
      }),
    );
    expect(workflows.map((w) => w.id)).toEqual(["real"]);
    expect(skipped).toEqual([
      { file: "empty-phases.yaml", reason: "`phases` is empty" },
      { file: "list.yml", reason: "not a YAML mapping" },
      { file: "pnpm-lock.yaml", reason: "no `phases` list" },
    ]);
  });

  it("fails when no top-level YAML is a workflow, naming every file it skipped", () => {
    const root = pkg({ "pnpm-lock.yaml": LOCKFILE, "vsa.yaml": "version: 1\n" });
    expect(() => resolvePackage(root)).toThrow(/No workflow definitions found/);
    expect(() => resolvePackage(root)).toThrow(/pnpm-lock\.yaml: no `phases` list/);
    expect(() => resolvePackage(root)).toThrow(/vsa\.yaml: no `phases` list/);
  });
});

describe("single and multi resolution", () => {
  it("rejects a workflow.yaml with no phases instead of resolving 0 of them", () => {
    expect(() => resolvePackage(pkg({ "workflow.yaml": "id: hollow\nname: Hollow\n" }))).toThrow(
      /workflow\.yaml is not a workflow definition: no `phases` list/,
    );
  });

  it("rejects a multi-package workflow with an empty phases list", () => {
    const root = pkg({
      "workflows/good/workflow.yaml": WORKFLOW,
      "workflows/hollow/workflow.yaml": "id: hollow\nphases: []\n",
    });
    expect(() => resolvePackage(root)).toThrow(/hollow[\\/]workflow\.yaml is not a workflow definition: `phases` is empty/);
  });
});

describe("install --dry-run on a directory of non-workflow YAML", () => {
  let stdout: string[];
  let stderr: string[];

  beforeEach(() => {
    stdout = [];
    stderr = [];
    vi.spyOn(process.stdout, "write").mockImplementation((s) => (stdout.push(String(s)), true));
    vi.spyOn(process.stderr, "write").mockImplementation((s) => (stderr.push(String(s)), true));
    vi.spyOn(console, "log").mockImplementation((s) => void stdout.push(String(s)));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fails resolution instead of calling the package valid", async () => {
    const root = pkg({ "pnpm-lock.yaml": LOCKFILE, "apss.yaml": "rules: []\n" });
    await expect(
      installCommand.handler({ positionals: [root], values: { "dry-run": true } }),
    ).rejects.toBeInstanceOf(CLIError);
    expect(stdout.join("")).not.toMatch(/package is valid/);
    expect(stderr.join("")).toMatch(/pnpm-lock\.yaml: no `phases` list/);
  });

  it("installs the real workflow and warns about each skipped file", async () => {
    const root = pkg({ "pnpm-lock.yaml": LOCKFILE, "real.yaml": WORKFLOW });
    await installCommand.handler({ positionals: [root], values: { "dry-run": true } });
    expect(stdout.join("")).toMatch(/package is valid/);
    expect(stdout.join("")).toMatch(/Workflows: 1\b/);
    expect(stderr.join("")).toMatch(/Skipped pnpm-lock\.yaml: no `phases` list/);
  });
});

describe("install on a package with a skipped file declaring claude_plugins", () => {
  let requests: Request[];

  beforeEach(() => {
    requests = [];
    vi.spyOn(process.stdout, "write").mockReturnValue(true);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
    vi.spyOn(console, "log").mockImplementation(() => undefined);
    // Only the HTTP boundary is faked: resolution and both preflights are real.
    vi.stubGlobal("fetch", async (input: Request | string, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      requests.push(request);
      if (request.url.includes("/claude-plugins/")) {
        // Already locked, so a lookup never goes on to clone or register.
        return Response.json({ name: "locked", version: "v1" });
      }
      return Response.json({ id: "real", name: "Real", status: "created", warnings: [] });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  const pluginPaths = (): string[] =>
    requests.map((r) => new URL(r.url).pathname).filter((p) => p.includes("/claude-plugins/"));

  async function uploadedIds(): Promise<string[]> {
    const uploads = requests.filter((r) => r.url.includes("/workflows/from-yaml"));
    return Promise.all(uploads.map(async (r) => ((await r.clone().json()) as { id: string }).id));
  }

  it("installs the real workflow when the skipped file's plugin ref is invalid", async () => {
    const root = pkg({ "real.yaml": WORKFLOW, "config.yaml": "claude_plugins:\n  - not-a-plugin-ref\n" });
    await installCommand.handler({ positionals: [root], values: {} });
    expect(await uploadedIds()).toEqual(["real"]);
    expect(pluginPaths()).toEqual([]);
  });

  it("looks up no plugin that only a skipped file declares", async () => {
    const root = pkg({ "real.yaml": WORKFLOW, "config.yaml": "claude_plugins:\n  - example/unused@v1\n" });
    await installCommand.handler({ positionals: [root], values: {} });
    expect(pluginPaths()).toEqual([]);
    expect(await uploadedIds()).toEqual(["real"]);
  });

  it("still resolves the plugins a retained workflow declares, at both scopes", async () => {
    const root = pkg({
      "real.yaml":
        "id: real\nname: Real\nclaude_plugins:\n  - example/top@v1\nphases:\n" +
        "  - id: build\n    prompt_template: go\n    claude_plugins:\n      - example/phase@v2\n",
      "config.yaml": "claude_plugins:\n  - example/unused@v1\n",
    });
    await installCommand.handler({ positionals: [root], values: {} });
    expect(pluginPaths().sort()).toEqual([
      "/api/v1/claude-plugins/phase/v2",
      "/api/v1/claude-plugins/top/v1",
    ]);
    expect(await uploadedIds()).toEqual(["real"]);
  });

  it("still rejects an invalid plugin ref in a retained workflow", async () => {
    const root = pkg({
      "real.yaml": "id: real\nname: Real\nclaude_plugins:\n  - not-a-plugin-ref\nphases:\n  - id: build\n    prompt_template: go\n",
    });
    await expect(installCommand.handler({ positionals: [root], values: {} })).rejects.toThrow(
      /not-a-plugin-ref/,
    );
    expect(await uploadedIds()).toEqual([]);
  });
});
