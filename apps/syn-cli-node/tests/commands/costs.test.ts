import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { costsGroup } from "../../src/commands/costs.js";
import { CLIError } from "../../src/framework/errors.js";

describe("costs commands", () => {
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

  it("summary shows cost overview", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        total_cost_usd: "5.00",
        total_sessions: 10,
        total_executions: 5,
        total_tokens: 50000,
        total_tool_calls: 100,
        top_models: [],
        top_sessions: [],
      }),
    );
    await costsGroup.getCommand("summary")!.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toContain("$5.00");
    expect(out).toContain("10");
  });

  it("session detail shows breakdown", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        session_id: "sess-1",
        total_cost_usd: "1.50",
        total_tokens: 20000,
        input_tokens: 15000,
        output_tokens: 5000,
        tool_calls: 20,
        turns: 10,
        duration_ms: 60000,
        started_at: "2026-01-01T00:00:00Z",
      }),
    );
    await costsGroup.getCommand("session")!.handler({ positionals: ["sess-1"], values: {} });
    const out = stdout();
    expect(out).toContain("sess-1");
    expect(out).toContain("$1.50");
  });

  it("session detail renders the unattributed bucket as unknown", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        session_id: "sess-2",
        total_cost_usd: "3.00",
        total_tokens: 20000,
        input_tokens: 15000,
        output_tokens: 5000,
        tool_calls: 20,
        turns: 10,
        duration_ms: 60000,
        started_at: "2026-01-01T00:00:00Z",
        cost_by_model: { "claude-opus-5-5": "2.00", "unattributed-model": "1.00" },
      }),
    );
    await costsGroup.getCommand("session")!.handler({ positionals: ["sess-2"], values: {} });
    const out = stdout();
    expect(out).toContain("claude-opus-5-5: $2.00");
    expect(out).toContain("unknown: $1.00");
    expect(out).not.toContain("unattributed-model");
  });

  it("summary renders typed top models", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        total_cost_usd: "5.00",
        total_sessions: 10,
        total_executions: 5,
        total_tokens: 50000,
        total_tool_calls: 100,
        top_models: [
          { model: "gpt-6-sol", cost_usd: "4.00" },
          { model: "unattributed-model", cost_usd: "1.00" },
        ],
        top_sessions: [],
      }),
    );
    await costsGroup.getCommand("summary")!.handler({ positionals: [], values: {} });
    const out = stdout();
    expect(out).toContain("gpt-6-sol");
    expect(out).toContain("$4.00");
    expect(out).toContain("unknown");
    expect(out).not.toContain("unattributed-model");
  });

  it("session detail throws on missing id", async () => {
    await expect(
      costsGroup.getCommand("session")!.handler({ positionals: [], values: {} }),
    ).rejects.toThrow(CLIError);
  });

  it("sessions list shows table", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse([
        { session_id: "sess-1", total_cost_usd: "0.50", total_tokens: 5000, duration_ms: 30000, tool_calls: 10 },
      ]),
    );
    await costsGroup.getCommand("sessions")!.handler({ positionals: [], values: {} });
    expect(stdout()).toContain("sess-1");
  });
});
