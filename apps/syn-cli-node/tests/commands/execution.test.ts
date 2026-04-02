import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { executionGroup } from "../../src/commands/execution.js";
import { CLIError } from "../../src/framework/errors.js";

describe("execution commands", () => {
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

  describe("list", () => {
    const handler = executionGroup.getCommand("list")!.handler;

    it("renders executions table", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          executions: [
            {
              workflow_execution_id: "exec-001",
              workflow_name: "my-workflow",
              status: "completed",
              started_at: "2026-01-01T00:00:00Z",
              completed_phases: 3,
              total_phases: 3,
              total_tokens: 5000,
              total_cost_usd: "0.05",
            },
          ],
          total: 1,
        }),
      );

      await handler({ positionals: [], values: {} });
      const out = stdout();
      expect(out).toContain("exec-001");
      expect(out).toContain("my-workflow");
      expect(out).toContain("3/3");
    });

    it("shows empty message when no executions", async () => {
      mockFetch.mockResolvedValue(jsonResponse({ executions: [], total: 0 }));
      await handler({ positionals: [], values: {} });
      expect(stdout()).toContain("No executions found");
    });
  });

  describe("show", () => {
    const handler = executionGroup.getCommand("show")!.handler;

    it("renders execution detail", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          workflow_execution_id: "exec-001",
          workflow_name: "test-wf",
          status: "completed",
          started_at: "2026-01-01T00:00:00Z",
          completed_at: "2026-01-01T01:00:00Z",
          total_tokens: 10000,
          total_cost_usd: "0.10",
          phases: [
            { name: "phase-1", status: "completed", started_at: "2026-01-01T00:00:00Z", total_tokens: 5000, cost_usd: "0.05" },
          ],
        }),
      );

      await handler({ positionals: ["exec-001"], values: {} });
      const out = stdout();
      expect(out).toContain("exec-001");
      expect(out).toContain("test-wf");
      expect(out).toContain("phase-1");
    });

    it("throws on missing execution-id", async () => {
      await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    });
  });
});
