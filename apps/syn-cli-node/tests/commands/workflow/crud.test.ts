import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  createCommand,
  listCommand,
  showCommand,
  deleteCommand,
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
            phases: [{ name: "build" }, { name: "test" }],
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
});
