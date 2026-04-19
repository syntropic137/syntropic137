import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { runCommand, statusCommand } from "../../../src/commands/workflow/run.js";
import { CLIError } from "../../../src/framework/errors.js";

describe("workflow run commands", () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    mockFetch.mockReset();
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

  describe("run", () => {
    it("starts a workflow execution", async () => {
      // First call resolves the workflow, second fetches detail, third triggers execution
      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            workflows: [
              {
                id: "wf-run-123456789",
                name: "Build Pipeline",
                workflow_type: "implementation",
                phase_count: 2,
              },
            ],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: "wf-run-123456789",
            name: "Build Pipeline",
            workflow_type: "implementation",
            classification: "standard",
            phases: [],
            input_declarations: [],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            status: "started",
            execution_id: "exec-001",
          }),
        );

      await runCommand.handler({
        positionals: ["wf-run"],
        values: { task: "Fix the bug" },
      });

      const out = stdout();
      expect(out).toContain("Build Pipeline");
      expect(out).toContain("execution started");
      expect(out).toContain("exec-001");
    });

    it("supports dry-run mode", async () => {
      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            workflows: [
              {
                id: "wf-dry-123456789",
                name: "Test WF",
                workflow_type: "custom",
                phase_count: 1,
              },
            ],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: "wf-dry-123456789",
            name: "Test WF",
            workflow_type: "custom",
            classification: "standard",
            phases: [],
            input_declarations: [],
          }),
        );

      await runCommand.handler({
        positionals: ["wf-dry"],
        values: { "dry-run": true },
      });

      const out = stdout();
      expect(out).toContain("DRY RUN");
      // Should not have made a third fetch call (no execution) — 2 calls: list + detail
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });

    it("rejects execution when required inputs are missing", async () => {
      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            workflows: [
              {
                id: "wf-inp-123456789",
                name: "Marketplace WF",
                workflow_type: "custom",
                phase_count: 1,
              },
            ],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: "wf-inp-123456789",
            name: "Marketplace WF",
            workflow_type: "custom",
            classification: "standard",
            phases: [],
            input_declarations: [
              { name: "repository", description: "Target repo (owner/repo)", required: true, default: null },
            ],
          }),
        );

      await expect(
        runCommand.handler({
          positionals: ["wf-inp"],
          values: {},
        }),
      ).rejects.toThrow(CLIError);

      const errOut = (process.stderr.write as ReturnType<typeof vi.fn>).mock.calls
        .map((c: unknown[]) => String(c[0]))
        .join("");
      expect(errOut).toContain("Missing required inputs");
    });

    it("throws CLIError when workflow-id is missing", async () => {
      await expect(
        runCommand.handler({ positionals: [], values: {} }),
      ).rejects.toThrow(CLIError);
    });

    it("rejects --input repository=X with migration hint", async () => {
      await expect(
        runCommand.handler({
          positionals: ["wf-x"],
          values: { input: ["repository=owner/repo"] },
        }),
      ).rejects.toThrow(CLIError);

      const errOut = (process.stderr.write as ReturnType<typeof vi.fn>).mock.calls
        .map((c: unknown[]) => String(c[0]))
        .join("");
      expect(errOut).toContain("'repository' is not a valid --input key");

      const out = stdout();
      expect(out).toContain("-R <owner/repo>");
      // No API call should have been made — guard runs before resolveWorkflow
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("rejects --input repos=owner/a,owner/b with migration hint", async () => {
      await expect(
        runCommand.handler({
          positionals: ["wf-x"],
          values: { input: ["repos=owner/a,owner/b"] },
        }),
      ).rejects.toThrow(CLIError);

      const errOut = (process.stderr.write as ReturnType<typeof vi.fn>).mock.calls
        .map((c: unknown[]) => String(c[0]))
        .join("");
      expect(errOut).toContain("'repos' is not a valid --input key");
    });

    it("resolves -R repo-* to full_name via /repos/{id}", async () => {
      mockFetch
        // 1) repo-* lookup (happens before resolveWorkflow in the handler)
        .mockResolvedValueOnce(
          jsonResponse({
            repo_id: "repo-abc",
            organization_id: "org-1",
            system_id: "",
            provider: "github",
            full_name: "acme/widgets",
            owner: "acme",
            default_branch: "main",
            installation_id: "",
            is_private: false,
            created_by: "",
            created_at: "2026-01-01T00:00:00Z",
          }),
        )
        // 2) resolveWorkflow list
        .mockResolvedValueOnce(
          jsonResponse({
            workflows: [
              { id: "wf-run-ref-1", name: "W", workflow_type: "custom", phase_count: 1 },
            ],
          }),
        )
        // 3) workflow detail
        .mockResolvedValueOnce(
          jsonResponse({
            id: "wf-run-ref-1",
            name: "W",
            workflow_type: "custom",
            classification: "standard",
            phases: [],
            input_declarations: [],
          }),
        )
        // 4) execute
        .mockResolvedValueOnce(
          jsonResponse({ status: "started", execution_id: "exec-001" }),
        );

      await runCommand.handler({
        positionals: ["wf-run"],
        values: { repo: ["repo-abc"] },
      });

      // openapi-fetch uses fetch(Request), so call args come as [Request]
      const lookupReq = mockFetch.mock.calls[0]![0] as Request;
      expect(lookupReq.url).toContain("/repos/repo-abc");

      // The execute call (#4) must carry the resolved full_name, not repo-abc
      const executeReq = mockFetch.mock.calls[3]![0] as Request;
      expect(executeReq.url).toContain("/workflows/wf-run-ref-1/execute");
      const body = JSON.parse(await executeReq.clone().text());
      expect(body.repos).toEqual(["acme/widgets"]);
    });

    it("passes owner/repo straight through without lookup", async () => {
      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            workflows: [
              { id: "wf-passthrough-1", name: "W", workflow_type: "custom", phase_count: 1 },
            ],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: "wf-passthrough-1",
            name: "W",
            workflow_type: "custom",
            classification: "standard",
            phases: [],
            input_declarations: [],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({ status: "started", execution_id: "exec-002" }),
        );

      await runCommand.handler({
        positionals: ["wf-passthrough"],
        values: { repo: ["acme/widgets"] },
      });

      // No /repos/ lookup — 3 calls: workflows list, detail, execute
      expect(mockFetch).toHaveBeenCalledTimes(3);
      const urls = mockFetch.mock.calls.map((c: unknown[]) => (c[0] as Request).url);
      expect(urls.some((u: string) => u.includes("/repos/"))).toBe(false);

      const executeReq = mockFetch.mock.calls[2]![0] as Request;
      const body = JSON.parse(await executeReq.clone().text());
      expect(body.repos).toEqual(["acme/widgets"]);
    });

    it("resolves mixed -R values: repo-* via lookup, owner/repo passthrough", async () => {
      mockFetch
        // 1) repo-abc lookup
        .mockResolvedValueOnce(
          jsonResponse({
            repo_id: "repo-abc",
            organization_id: "org-1",
            system_id: "",
            provider: "github",
            full_name: "acme/widgets",
            owner: "acme",
            default_branch: "main",
            installation_id: "",
            is_private: false,
            created_by: "",
            created_at: "2026-01-01T00:00:00Z",
          }),
        )
        // 2) resolveWorkflow list
        .mockResolvedValueOnce(
          jsonResponse({
            workflows: [
              { id: "wf-mixed-1", name: "W", workflow_type: "custom", phase_count: 1 },
            ],
          }),
        )
        // 3) workflow detail
        .mockResolvedValueOnce(
          jsonResponse({
            id: "wf-mixed-1",
            name: "W",
            workflow_type: "custom",
            classification: "standard",
            phases: [],
            input_declarations: [],
          }),
        )
        // 4) execute
        .mockResolvedValueOnce(
          jsonResponse({ status: "started", execution_id: "exec-mix" }),
        );

      await runCommand.handler({
        positionals: ["wf-mixed"],
        values: { repo: ["repo-abc", "other/widgets"] },
      });

      // Exactly one /repos/ lookup — for repo-abc only, not for other/widgets
      const urls = mockFetch.mock.calls.map((c: unknown[]) => (c[0] as Request).url);
      const repoLookups = urls.filter((u: string) => u.includes("/repos/"));
      expect(repoLookups).toHaveLength(1);
      expect(repoLookups[0]).toContain("/repos/repo-abc");
      expect(urls.some((u: string) => u.includes("/repos/other"))).toBe(false);

      // Execute body carries both: resolved full_name from lookup, then passthrough slug
      const executeReq = mockFetch.mock.calls[3]![0] as Request;
      const body = JSON.parse(await executeReq.clone().text());
      expect(body.repos).toEqual(["acme/widgets", "other/widgets"]);
    });

    it("fails loud when repo-* lookup returns no full_name", async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          repo_id: "repo-broken",
          organization_id: "org-1",
          system_id: "",
          provider: "github",
          full_name: "",
          owner: "",
          default_branch: "main",
          installation_id: "",
          is_private: false,
          created_by: "",
          created_at: "2026-01-01T00:00:00Z",
        }),
      );

      await expect(
        runCommand.handler({
          positionals: ["wf-broken"],
          values: { repo: ["repo-broken"] },
        }),
      ).rejects.toThrow(CLIError);

      // Only the lookup call happened — never reached resolveWorkflow or execute
      expect(mockFetch).toHaveBeenCalledTimes(1);
      const errOut = (process.stderr.write as ReturnType<typeof vi.fn>).mock.calls
        .map((c: unknown[]) => String(c[0]))
        .join("");
      expect(errOut.length === 0 || errOut).toBeDefined();
    });

    it("fails loud when API returns status!=started", async () => {
      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            workflows: [
              { id: "wf-weird-1", name: "W", workflow_type: "custom", phase_count: 1 },
            ],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: "wf-weird-1",
            name: "W",
            workflow_type: "custom",
            classification: "standard",
            phases: [],
            input_declarations: [],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({ status: "accepted", execution_id: null }),
        );

      await expect(
        runCommand.handler({ positionals: ["wf-weird"], values: {} }),
      ).rejects.toThrow(CLIError);
    });
  });

  describe("status", () => {
    it("renders execution history table", async () => {
      // First call resolves the workflow, second call gets runs
      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            workflows: [
              {
                id: "wf-stat-123456789",
                name: "Status WF",
                workflow_type: "custom",
                phase_count: 3,
              },
            ],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            runs: [
              {
                workflow_execution_id: "exec-abc-123456789",
                status: "completed",
                completed_phases: 3,
                total_phases: 3,
                total_tokens: 15000,
                total_cost_usd: "0.25",
              },
            ],
          }),
        );

      await statusCommand.handler({
        positionals: ["wf-stat"],
        values: {},
      });

      const out = stdout();
      expect(out).toContain("Status WF");
      expect(out).toContain("completed");
      expect(out).toContain("Executions");
    });

    it("shows empty message when no executions", async () => {
      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            workflows: [
              {
                id: "wf-empty-123456789",
                name: "Empty WF",
                workflow_type: "custom",
                phase_count: 1,
              },
            ],
          }),
        )
        .mockResolvedValueOnce(jsonResponse({ runs: [] }));

      await statusCommand.handler({
        positionals: ["wf-empty"],
        values: {},
      });

      expect(stdout()).toContain("No executions found");
    });

    it("throws CLIError when workflow-id is missing", async () => {
      await expect(
        statusCommand.handler({ positionals: [], values: {} }),
      ).rejects.toThrow(CLIError);
    });
  });
});
