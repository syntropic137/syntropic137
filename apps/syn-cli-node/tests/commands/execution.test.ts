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
            { name: "phase-1", status: "completed", started_at: "2026-01-01T00:00:00Z", total_tokens: 5000, cost_usd: "0.05", model: "claude-opus-5-5", requested_model: "opus", model_display: "claude-opus-5-5" },
            { name: "phase-2", status: "completed", started_at: "2026-01-01T00:30:00Z", total_tokens: 5000, cost_usd: "0.05", model: null, requested_model: "gpt-sol", model_display: "unknown (requested: gpt-sol)" },
          ],
        }),
      );

      await handler({ positionals: ["exec-001"], values: {} });
      const out = stdout();
      expect(out).toContain("exec-001");
      expect(out).toContain("test-wf");
      expect(out).toContain("phase-1");
      // The phase table names what RAN (ADR-067 D9).
      expect(out).toContain("claude-opus-5-5");
      expect(out).toContain("unknown (requested: gpt-sol)");
    });

    const detail = {
      workflow_execution_id: "exec-001", workflow_name: "test-wf", status: "completed",
      started_at: "2026-01-01T00:00:00Z", total_tokens: 1, total_cost_usd: "0.01", phases: [],
    };

    it("prints the server inventory summary and the follow-up command", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(detail)).mockResolvedValueOnce(jsonResponse({
        run: { source_instance_id: "src", execution_id: "exec-001" }, snapshot: null,
        reconstruction_status: "current", observed_evidence_watermark: 0, later_evidence_pending: false,
        summary: {
          complete: false, coverage_state: "open", coverage_display: "open: more sessions may still appear",
          counts_display: "2 platform sessions, 3 native transcripts (claude 3), 0 invocations, 1 gap",
          follow_up_command: "syn execution sessions exec-001 --all", remote_replication: "disabled",
          revision: "r", distinct_sessions: 5, platform_sessions: 2, invocations: 0, native_transcripts: 3, gaps: 1, namespaces: [],
        },
      }));
      await handler({ positionals: ["exec-001"], values: {} });
      const out = stdout();
      expect(out).toContain("2 platform sessions, 3 native transcripts (claude 3), 0 invocations, 1 gap");
      expect(out).toContain("open: more sessions may still appear (incomplete)");
      expect(out).toContain("syn execution sessions exec-001 --all");
      const second = new URL((mockFetch.mock.calls[1]![0] as Request).url);
      expect(second.pathname).toMatch(/\/executions\/exec-001\/session-inventory$/);
    });

    it("still shows the execution when the inventory cannot be read", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(detail)).mockResolvedValueOnce(jsonResponse({ detail: "denied" }, 403));
      await handler({ positionals: ["exec-001"], values: {} });
      expect(stdout()).toContain("test-wf");
      expect(stdout()).toContain("Session inventory: unavailable (403)");
    });

    it("throws on missing execution-id", async () => {
      await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    });
  });
});
