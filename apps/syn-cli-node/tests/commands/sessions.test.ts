import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionsGroup } from "../../src/commands/sessions.js";
import { CLIError } from "../../src/framework/errors.js";

describe("sessions commands", () => {
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

  it("list shows sessions table", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        sessions: [
          {
            id: "sess-001",
            workflow_id: "wf-1",
            phase_id: null,
            status: "completed",
            agent_provider: "claude",
            agent_model: "claude-sonnet-4-6",
            agent_model_display: "Sonnet 4.6",
            total_tokens: 5000,
            total_tokens_display: "5.0k",
            total_cost_usd: "0.05",
            total_cost_display: "$0.05",
            duration_seconds: 12.5,
            duration_display: "12s",
            started_at: "2026-01-01T00:00:00Z",
          },
        ],
        total: 1,
      }),
    );

    await sessionsGroup.getCommand("list")!.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toContain("sess-001");
    expect(out).toContain("Sonnet 4.6");
    expect(out).toContain("5.0k");
    expect(out).toContain("$0.05");
  });

  it("list shows empty message", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ sessions: [], total: 0 }));
    await sessionsGroup.getCommand("list")!.handler({ positionals: [], values: {} });
    expect(stdout()).toContain("No sessions found");
  });

  it("show renders session detail", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        id: "sess-001",
        workflow_id: "wf-1",
        workflow_name: "test-wf",
        phase_id: null,
        milestone_id: null,
        agent_provider: "claude",
        agent_model: "claude-sonnet-4-6",
        agent_model_display: "Sonnet 4.6",
        status: "completed",
        input_tokens: 8000,
        input_tokens_display: "8.0k",
        output_tokens: 2000,
        output_tokens_display: "2.0k",
        cache_creation_tokens: 0,
        cache_creation_tokens_display: "0",
        cache_read_tokens: 0,
        cache_read_tokens_display: "0",
        total_tokens: 10000,
        total_tokens_display: "10.0k",
        total_cost_usd: "0.10",
        total_cost_display: "$0.10",
        duration_seconds: 134.2,
        duration_display: "2m 14s",
        operations: [],
        started_at: "2026-01-01T00:00:00Z",
      }),
    );

    await sessionsGroup.getCommand("show")!.handler({ positionals: ["sess-001"], values: {} });
    const out = stdout();
    expect(out).toContain("sess-001");
    expect(out).toContain("test-wf");
    expect(out).toContain("Sonnet 4.6");
    expect(out).toContain("10.0k");
    expect(out).toContain("$0.10");
    expect(out).toContain("2m 14s");
  });

  it("show throws on missing session-id", async () => {
    await expect(
      sessionsGroup.getCommand("show")!.handler({ positionals: [], values: {} }),
    ).rejects.toThrow(CLIError);
  });
});
