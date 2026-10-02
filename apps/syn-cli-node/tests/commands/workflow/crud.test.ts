import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  createCommand,
  listCommand,
  showCommand,
  deleteCommand,
  validateCommand,
} from "../../../src/commands/workflow/crud.js";
import { CLIError } from "../../../src/framework/errors.js";

describe("workflow crud commands", () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
    vi.spyOn(process.stdout, "write").mockReturnValue(true);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetAllMocks();
    vi.unstubAllGlobals();
  });

  function jsonResponse(data: unknown, status = 200): Response {
    return new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  function stdout(): string {
    return (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls
      .map((c: unknown[]) => String(c[0]))
      .join("");
  }

  describe("create", () => {
    it("creates a workflow and prints ID", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({ id: "wf-new-001", name: "My Workflow" }),
      );

      await createCommand.handler({
        positionals: ["My Workflow"],
        values: { type: "research", repo: "https://github.com/test/repo" },
      });

      const out = stdout();
      expect(out).toContain("Created workflow");
      expect(out).toContain("My Workflow");
      expect(out).toContain("wf-new-001");
    });

    it("throws CLIError when name is missing", async () => {
      await expect(
        createCommand.handler({ positionals: [], values: {} }),
      ).rejects.toThrow(CLIError);
    });
  });

  describe("create --from", () => {
    let tmpDir: string;
    let yamlPath: string;
    const originalArgv = process.argv;

    beforeEach(() => {
      tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "syn-crud-from-"));
      yamlPath = path.join(tmpDir, "workflow.yaml");
      fs.writeFileSync(
        yamlPath,
        "id: upload-test\nname: Upload Test\ntype: custom\nphases:\n  - id: p1\n    name: Phase\n    order: 1\n",
        "utf-8",
      );
    });

    afterEach(() => {
      fs.rmSync(tmpDir, { recursive: true, force: true });
      process.argv = originalArgv;
    });

    it("uploads YAML bytes via postYaml and prints created workflow", async () => {
      process.argv = ["node", "syn", "workflow", "create", "My Upload", "--from", yamlPath];
      mockFetch.mockResolvedValue(
        jsonResponse(
          { id: "upload-test", name: "Upload Test", workflow_type: "custom", status: "created" },
          201,
        ),
      );

      await createCommand.handler({
        positionals: ["My Upload"],
        values: { from: yamlPath },
      });

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const call = mockFetch.mock.calls[0]!;
      const url = String(call[0]);
      const init = call[1] as RequestInit;
      expect(url).toContain("/workflows/from-yaml");
      expect(url).toContain("name=My+Upload");
      expect(init.method).toBe("POST");
      const headers = init.headers as Record<string, string>;
      expect(headers["Content-Type"]).toBe("application/yaml");
      const body = init.body;
      const bytes = body instanceof Uint8Array ? body : new Uint8Array(body as ArrayBuffer);
      expect(Buffer.from(bytes).toString("utf-8")).toContain("upload-test");

      const out = stdout();
      expect(out).toContain("Created workflow");
      expect(out).toContain("Upload Test");
    });

    it("rejects --from combined with --repo", async () => {
      process.argv = [
        "node", "syn", "workflow", "create", "X",
        "--from", yamlPath,
        "--repo", "https://github.com/foo/bar",
      ];

      await expect(
        createCommand.handler({
          positionals: ["X"],
          values: { from: yamlPath, repo: "https://github.com/foo/bar" },
        }),
      ).rejects.toThrow(CLIError);
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("rejects --from combined with --type", async () => {
      process.argv = [
        "node", "syn", "workflow", "create", "X",
        "--from", yamlPath,
        "--type", "research",
      ];

      await expect(
        createCommand.handler({
          positionals: ["X"],
          values: { from: yamlPath, type: "research" },
        }),
      ).rejects.toThrow(CLIError);
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("rejects --from combined with short flag -r", async () => {
      process.argv = [
        "node", "syn", "workflow", "create", "X",
        "--from", yamlPath,
        "-r", "https://github.com/foo/bar",
      ];

      await expect(
        createCommand.handler({
          positionals: ["X"],
          values: { from: yamlPath, repo: "https://github.com/foo/bar" },
        }),
      ).rejects.toThrow(CLIError);
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("rejects --from when file does not exist", async () => {
      const missing = path.join(tmpDir, "does-not-exist.yaml");
      process.argv = ["node", "syn", "workflow", "create", "X", "--from", missing];

      await expect(
        createCommand.handler({
          positionals: ["X"],
          values: { from: missing },
        }),
      ).rejects.toThrow(CLIError);
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("rejects --from pointing at a directory", async () => {
      process.argv = ["node", "syn", "workflow", "create", "X", "--from", tmpDir];

      await expect(
        createCommand.handler({
          positionals: ["X"],
          values: { from: tmpDir },
        }),
      ).rejects.toThrow(CLIError);
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("respects -- end-of-options: literal --repo after -- is not a conflict", async () => {
      process.argv = [
        "node", "syn", "workflow", "create", "My Upload",
        "--from", yamlPath,
        "--", "--repo=ignored-literal",
      ];
      mockFetch.mockResolvedValue(
        jsonResponse(
          {
            id: "upload-test",
            name: "Upload Test",
            workflow_type: "custom",
            classification: "standard",
            repository_url: "",
            requires_repos: false,
            status: "created",
          },
          201,
        ),
      );

      await createCommand.handler({
        positionals: ["My Upload"],
        values: { from: yamlPath },
      });
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
  });

  describe("list", () => {
    it("renders workflows table", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          workflows: [
            {
              id: "wf-abc-123456789",
              name: "Deploy Pipeline",
              workflow_type: "deployment",
              phase_count: 3,
            },
          ],
        }),
      );

      await listCommand.handler({ positionals: [], values: {} });

      const out = stdout();
      expect(out).toContain("Deploy Pipeline");
      expect(out).toContain("deployment");
    });

    it("shows empty message when no workflows", async () => {
      mockFetch.mockResolvedValue(jsonResponse({ workflows: [] }));

      await listCommand.handler({ positionals: [], values: {} });

      expect(stdout()).toContain("No workflows found");
    });
  });

  describe("show", () => {
    it("renders workflow detail", async () => {
      // First call resolves the workflow (list endpoint)
      // Second call fetches the detail
      mockFetch
        // resolveWorkflow probes GET /workflows/{id} first (issue #880);
        // a prefix or absent id misses, then it falls back to the list.
        .mockResolvedValueOnce(jsonResponse({ detail: "Not found" }, 404))
        .mockResolvedValueOnce(
          jsonResponse({
            workflows: [
              {
                id: "wf-abc-123456789",
                name: "Test Workflow",
                workflow_type: "custom",
                phase_count: 2,
              },
            ],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: "wf-abc-123456789",
            name: "Test Workflow",
            workflow_type: "custom",
            classification: "single-phase",
            phases: [
              { name: "build", model: "gpt-sol", model_display: "gpt-sol → gpt-6-sol" },
              { name: "test" },
            ],
            input_declarations: [
              { name: "pr_number", required: true, description: "Pull request number" },
              { name: "branch", required: false, description: "Target branch", default: "main" },
            ],
          }),
        );

      await showCommand.handler({
        positionals: ["wf-abc"],
        values: {},
      });

      const out = stdout();
      expect(out).toContain("Test Workflow");
      expect(out).toContain("Workflow Details");
      expect(out).toContain("build");
      expect(out).toContain("test");
      // A definition surface shows what its alias resolves to.
      expect(out).toContain("gpt-sol → gpt-6-sol");
      // Regression: show must display required inputs so users know what --input flags to pass
      expect(out).toContain("pr_number");
      expect(out).toContain("required");
      expect(out).toContain("branch");
    });

    it("throws CLIError when workflow-id is missing", async () => {
      await expect(
        showCommand.handler({ positionals: [], values: {} }),
      ).rejects.toThrow(CLIError);
    });
  });

  describe("delete", () => {
    it("archives workflow with --force", async () => {
      // First call resolves the workflow, second call deletes
      mockFetch
        // resolveWorkflow probes GET /workflows/{id} first (issue #880);
        // a prefix or absent id misses, then it falls back to the list.
        .mockResolvedValueOnce(jsonResponse({ detail: "Not found" }, 404))
        .mockResolvedValueOnce(
          jsonResponse({
            workflows: [
              {
                id: "wf-del-123456789",
                name: "Old Workflow",
                workflow_type: "custom",
                phase_count: 1,
              },
            ],
          }),
        )
        .mockResolvedValueOnce(jsonResponse({}));

      await deleteCommand.handler({
        positionals: ["wf-del"],
        values: { force: true },
      });

      const out = stdout();
      expect(out).toContain("Archived workflow");
      expect(out).toContain("Old Workflow");
    });

    it("throws CLIError without --force", async () => {
      // resolveWorkflow probes GET /workflows/{id} first (issue #880); the
      // prefix misses, then it falls back to the list.
      mockFetch.mockResolvedValueOnce(jsonResponse({ detail: "Not found" }, 404));
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          workflows: [
            {
              id: "wf-del-123456789",
              name: "Old Workflow",
              workflow_type: "custom",
              phase_count: 1,
            },
          ],
        }),
      );

      await expect(
        deleteCommand.handler({
          positionals: ["wf-del"],
          values: { force: false },
        }),
      ).rejects.toThrow(CLIError);
    });

    it("throws CLIError when workflow-id is missing", async () => {
      await expect(
        deleteCommand.handler({ positionals: [], values: {} }),
      ).rejects.toThrow(CLIError);
    });
  });

  // A retired phase key (can_open_pr, #1477) is accepted and ignored by the
  // server, which says so in `warnings`. Each command that reads authored YAML
  // must show that, or the author never learns the line can go.
  describe("retired-key warnings", () => {
    const NOTICE = "phase 'open_pr': 'can_open_pr' is retired (#1477) and ignored";
    let tmpDir: string;

    beforeEach(() => {
      tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "syn-crud-warn-"));
    });

    afterEach(() => {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    });

    function requestOf(call: unknown[]): { url: string; body: Promise<string> } {
      const first = call[0] as Request | string;
      if (typeof first === "string") {
        return { url: first, body: Promise.resolve(String((call[1] as RequestInit).body)) };
      }
      return { url: first.url, body: first.clone().text() };
    }

    function writePackage(): string {
      const pkg = path.join(tmpDir, "pkg");
      fs.mkdirSync(pkg);
      fs.writeFileSync(
        path.join(pkg, "workflow.yaml"),
        "id: retired-pkg\nname: Retired Pkg\ntype: custom\nphases:\n" +
          "  - id: open_pr\n    name: Open PR\n    order: 1\n" +
          "    prompt_template: Open it.\n    can_open_pr: true\n",
        "utf-8",
      );
      return pkg;
    }

    it("validate <file> prints the server's warnings on a valid file", async () => {
      const file = path.join(tmpDir, "wf.yaml");
      fs.writeFileSync(file, "id: x\n", "utf-8");
      mockFetch.mockResolvedValue(
        jsonResponse({ valid: true, name: "X", workflow_type: "custom", phase_count: 1, warnings: [NOTICE] }),
      );

      await validateCommand.handler({ positionals: [file], values: {} });

      expect(stdout()).toContain("warning:");
      expect(stdout()).toContain(NOTICE);
    });

    it("validate <file> still prints warnings when the file is invalid", async () => {
      const file = path.join(tmpDir, "wf.yaml");
      fs.writeFileSync(file, "id: x\n", "utf-8");
      mockFetch.mockResolvedValue(
        jsonResponse({ valid: false, phase_count: 0, errors: ["bad"], warnings: [NOTICE] }),
      );

      await expect(validateCommand.handler({ positionals: [file], values: {} })).rejects.toThrow(
        CLIError,
      );
      expect(stdout()).toContain(NOTICE);
    });

    it("validate <dir> sends each resolved definition to the server", async () => {
      const pkg = writePackage();
      mockFetch.mockResolvedValue(
        jsonResponse({ valid: true, name: "Retired Pkg", workflow_type: "custom", phase_count: 1, warnings: [NOTICE] }),
      );

      await validateCommand.handler({ positionals: [pkg], values: {} });

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const { url, body } = requestOf(mockFetch.mock.calls[0]!);
      expect(url).toContain("/workflows/validate");
      const sent = JSON.parse(await body) as { content: string; filename: string };
      expect(JSON.parse(sent.content)).toMatchObject({ id: "retired-pkg" });
      expect(sent.filename).toBe("Retired Pkg.json");
      expect(stdout()).toContain(NOTICE);
      expect(stdout()).toContain("Valid single package");
    });

    it("validate <dir> fails when the server refuses a workflow", async () => {
      const pkg = writePackage();
      mockFetch.mockResolvedValue(
        jsonResponse({ valid: false, phase_count: 0, errors: ["Extra inputs are not permitted"] }),
      );

      await expect(validateCommand.handler({ positionals: [pkg], values: {} })).rejects.toThrow(
        CLIError,
      );
      expect(stdout()).toContain("Extra inputs are not permitted");
      expect(stdout()).not.toContain("Valid single package");
    });

    it("create --from prints the server's warnings", async () => {
      const file = path.join(tmpDir, "workflow.yaml");
      fs.writeFileSync(file, "id: x\n", "utf-8");
      const originalArgv = process.argv;
      process.argv = ["node", "syn", "workflow", "create", "X", "--from", file];
      mockFetch.mockResolvedValue(
        jsonResponse({ id: "x", name: "X", workflow_type: "custom", status: "created", warnings: [NOTICE] }, 201),
      );

      try {
        await createCommand.handler({ positionals: ["X"], values: { from: file } });
      } finally {
        process.argv = originalArgv;
      }

      expect(stdout()).toContain(NOTICE);
    });
  });
});
