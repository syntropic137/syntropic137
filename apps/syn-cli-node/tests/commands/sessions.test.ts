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
            total_tokens: 5000,
            total_cost_usd: "0.05",
            started_at: "2026-01-01T00:00:00Z",
          },
        ],
        total: 1,
      }),
    );

    await sessionsGroup.getCommand("list")!.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toContain("sess-001");
    expect(out).toContain("claude");
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
        status: "completed",
        input_tokens: 8000,
        output_tokens: 2000,
        total_tokens: 10000,
        total_cost_usd: "0.10",
        operations: [],
        started_at: "2026-01-01T00:00:00Z",
      }),
    );

    await sessionsGroup.getCommand("show")!.handler({ positionals: ["sess-001"], values: {} });
    const out = stdout();
    expect(out).toContain("sess-001");
    expect(out).toContain("test-wf");
  });

  it("show throws on missing session-id", async () => {
    await expect(
      sessionsGroup.getCommand("show")!.handler({ positionals: [], values: {} }),
    ).rejects.toThrow(CLIError);
  });
});
