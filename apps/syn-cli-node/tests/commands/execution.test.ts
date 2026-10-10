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
              // Certified at its first review (PC-63): 6 of 10 defined
              // phases ran, and the 4 repair phases were never needed.
              completed_phases: 6,
              total_phases: 10,
              phase_progress: {
                completed: 6,
                skipped: 4,
                possible: 6,
                remaining_possible: 0,
                percent: 100,
                display: "6 of 6 (4 phases not needed)",
              },
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
      // The API's progress, verbatim; the CLI never divides the raw counts.
      expect(out).toContain("6 of 6 (4 phases not needed)");
      expect(out).not.toContain("6/10");
    });

    it("sends every --tag as a repeated ?tag= query parameter (#967)", async () => {
      mockFetch.mockResolvedValue(jsonResponse({ executions: [], total: 0 }));
      await handler({ positionals: [], values: { tag: ["nightly", "eval-a"] } });
      const url = new URL((mockFetch.mock.calls[0]![0] as Request).url);
      expect(url.searchParams.getAll("tag")).toEqual(["nightly", "eval-a"]);
    });

    it("sends no tag parameter without --tag", async () => {
      mockFetch.mockResolvedValue(jsonResponse({ executions: [], total: 0 }));
      await handler({ positionals: [], values: {} });
      const url = new URL((mockFetch.mock.calls[0]![0] as Request).url);
      expect(url.searchParams.has("tag")).toBe(false);
    });

    it("shows a queued start's place and reason, and the budget (PC-124)", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          executions: [
            {
              workflow_execution_id: "exec-q1",
              workflow_name: "my-workflow",
              status: "queued",
              started_at: null,
              phase_progress: { completed: 0, skipped: 0, possible: 0, remaining_possible: 0, percent: 0, display: "0 of 0" },
              total_tokens: 0,
              total_cost_usd: "0",
              start_queue: {
                path: "direct", position: 1, held: true, running: 4, waiting: 2, limit: 4,
                queued_at: "2026-10-08T00:00:00Z",
                position_display: "queued 1 of 2 (4/4 running)",
                reason_display: "slots full 4/4",
              },
            },
          ],
          total: 1,
          budget: { running: 4, queued: 2, limit: 4, admission_paused: false, display: "4 running / 2 queued / cap 4" },
        }),
      );

      await handler({ values: { status: "queued" }, positionals: [] });

      expect((mockFetch.mock.calls[0]![0] as Request).url).toContain("status=queued");
      const out = stdout();
      expect(out).toContain("queued 1 of 2 (4/4 running): slots full 4/4");
      expect(out).toContain("Budget: 4 running / 2 queued / cap 4");
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
            { name: "phase-2", status: "completed", started_at: "2026-01-01T00:30:00Z", total_tokens: 5000, cost_usd: "0.05", model: null, requested_model: "gpt-sol", model_display: "gpt-sol (requested)" },
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
      expect(out).toContain("gpt-sol (requested)");
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
      expect(stdout()).toContain("Session inventory: unavailable (403): denied");
    });

    describe("outcome (#1501 A)", () => {
      /** What `show` printed for one detail, inventory unavailable. */
      async function show(over: Record<string, unknown>): Promise<string> {
        mockFetch
          .mockResolvedValueOnce(jsonResponse({ ...detail, ...over }))
          .mockResolvedValueOnce(jsonResponse({ detail: "denied" }, 403));
        await handler({ positionals: ["exec-001"], values: {} });
        return stdout().replace(/\x1b\[[0-9;]*m/g, "");
      }

      function phase(over: Record<string, unknown>): Record<string, unknown> {
        return {
          phase_id: "p", name: "review", status: "completed", started_at: "2026-01-01T00:00:00Z",
          total_tokens: 1, cost_usd: "0.01", model: null, requested_model: null, model_display: "m",
          ...over,
        };
      }

      it.each([
        // The VPS runs #1501 names: completed without a deliverable, and with one.
        [{ deliverable_produced: false, reported_side_effects: "succeeded" }, "no", "succeeded"],
        [{ deliverable_produced: true, reported_side_effects: "denied" }, "yes", "denied"],
        [{ deliverable_produced: true, reported_side_effects: "none" }, "yes", "none"],
        [{ deliverable_produced: false, reported_side_effects: "failed" }, "no", "failed"],
        // Said nothing is not "none": "none" is a claim the agent did not make.
        [{ deliverable_produced: false, reported_side_effects: null }, "no", "not reported"],
        [{ deliverable_produced: true }, "yes", "not reported"],
      ])("renders %o as Deliverable %s, Side effects %s", async (over, deliverable, sideEffects) => {
        const out = await show(over);
        expect(out).toContain(`  Deliverable:  ${deliverable}\n`);
        expect(out).toContain(`  Side effects: ${sideEffects}\n`);
      });

      it("renders each phase's reported side effects", async () => {
        const out = await show({
          phases: [
            phase({ name: "implement", reported_side_effects: "denied" }),
            phase({ name: "review", reported_side_effects: null }),
          ],
        });
        const rows = out.split("\n");
        expect(rows.find((r) => r.includes("implement"))).toMatch(/denied\s*$/);
        expect(rows.find((r) => r.includes("review"))).toMatch(/not reported\s*$/);
      });

      it("names why a failed execution and its failed phase failed", async () => {
        const out = await show({
          status: "failed",
          error_message: "agent exited with code 124",
          failure_classification: "platform",
          reported_failure_reason: null,
          phases: [
            phase({ name: "research", status: "completed" }),
            phase({
              name: "implement",
              status: "failed",
              error_message: "agent exited with code 124",
              failure_classification: "platform",
              reported_failure_reason: null,
            }),
          ],
        });
        expect(out).toContain("  Failure:      platform\n");
        expect(out).toContain("  Error:        agent exited with code 124\n");
        expect(out).toContain("  ✗ implement: platform\n    agent exited with code 124\n");
        expect(out).not.toContain("✗ research");
      });

      it("shows the agent's reported reason beside the classification, never as it", async () => {
        const out = await show({
          status: "failed",
          error_message: "Phase implement reported failure",
          failure_classification: "correct_refusal",
          reported_failure_reason: "task",
          phases: [
            phase({
              name: "implement",
              status: "failed",
              error_message: "Phase implement reported failure",
              failure_classification: "correct_refusal",
              reported_failure_reason: "task",
            }),
          ],
        });
        expect(out).toContain("  Failure:      correct_refusal (agent reported: task)\n");
        expect(out).toContain("  ✗ implement: correct_refusal (agent reported: task)\n");
      });

      it("says so when a failed phase recorded no error text", async () => {
        const out = await show({
          status: "failed",
          failure_classification: "unclassified",
          phases: [phase({ name: "implement", status: "failed", error_message: null })],
        });
        expect(out).toContain("  ✗ implement: unclassified\n    no error recorded\n");
      });

      it("prints no Failure line for a run that did not fail", async () => {
        const out = await show({ status: "completed", failure_classification: "unclassified" });
        expect(out).not.toContain("Failure:");
      });

      it("marks a phase whose deliverable was recovered, and only that phase", async () => {
        const out = await show({
          phases: [
            phase({ name: "implement", deliverable_recovered: true }),
            phase({ name: "review", deliverable_recovered: false }),
          ],
        });
        const rows = out.split("\n");
        expect(rows.find((r) => r.includes("implement"))).toContain("completed (recovered)");
        expect(rows.find((r) => r.includes("review"))).not.toContain("recovered");
      });
    });

    it("prints a resume start that failed, with its reason and attempts", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({
        ...detail,
        resume_start: {
          status: "failed", status_reason: "artifact art-1 not found", attempts: 3, max_attempts: 3,
          recorded_at: "2026-01-01T00:00:00Z", dispatched_at: null,
        },
      })).mockResolvedValueOnce(jsonResponse({ detail: "denied" }, 403));
      await handler({ positionals: ["exec-001"], values: {} });
      const out = stdout();
      expect(out).toContain("Resume start:");
      expect(out).toContain("failed");
      expect(out).toContain("3/3");
      expect(out).toContain("artifact art-1 not found");
    });

    it("prints a queued execution with its place in the budget (#1557)", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({
        ...detail,
        status: "queued",
        start_queue: {
          path: "direct", position: 2, running: 4, waiting: 3, limit: 4,
          queued_at: "2026-01-01T00:00:00Z", position_display: "queued 2 of 3 (4/4 running)",
        },
      })).mockResolvedValueOnce(jsonResponse({ detail: "denied" }, 403));
      await handler({ positionals: ["exec-001"], values: {} });
      const out = stdout();
      expect(out).toContain("queued");
      expect(out).toContain("Queue:");
      expect(out).toContain("queued 2 of 3 (4/4 running) via direct");
    });

    it("prints a resume start waiting for a slot, not just dispatched (#1557)", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({
        ...detail,
        resume_start: {
          status: "dispatched", status_reason: null, attempts: 0, max_attempts: 3,
          recorded_at: "2026-01-01T00:00:00Z", dispatched_at: "2026-01-01T00:00:01Z",
          start_queue: {
            path: "resume", position: 1, running: 1, waiting: 5, limit: 1,
            queued_at: "2026-01-01T00:00:01Z", position_display: "queued 1 of 5 (1/1 running)",
          },
        },
      })).mockResolvedValueOnce(jsonResponse({ detail: "denied" }, 403));
      await handler({ positionals: ["exec-001"], values: {} });
      expect(stdout()).toContain("queued 1 of 5 (1/1 running) via resume");
    });

    it("prints a durable direct start no process holds yet, after a restart (#1557)", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({
        ...detail,
        status: "queued",
        start_queue: {
          path: "direct", position: null, held: false, running: 0, waiting: 0, limit: 4,
          start_status: "pending", status_reason: null,
          queued_at: "2026-01-01T00:00:00Z", position_display: "recorded, pending (0/4 running)",
        },
      })).mockResolvedValueOnce(jsonResponse({ detail: "denied" }, 403));
      await handler({ positionals: ["exec-001"], values: {} });
      expect(stdout()).toContain("recorded, pending (0/4 running) via direct");
    });

    it("prints no queue line for an execution that exists", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ ...detail, start_queue: null }))
        .mockResolvedValueOnce(jsonResponse({ detail: "denied" }, 403));
      await handler({ positionals: ["exec-001"], values: {} });
      expect(stdout()).not.toContain("Queue:");
    });

    it("prints no resume start for an execution that was never resumed", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ ...detail, resume_start: null }))
        .mockResolvedValueOnce(jsonResponse({ detail: "denied" }, 403));
      await handler({ positionals: ["exec-001"], values: {} });
      expect(stdout()).not.toContain("Resume start:");
    });

    it("throws on missing execution-id", async () => {
      await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    });
  });
});
