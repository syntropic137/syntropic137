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
