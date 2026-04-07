import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { triggersGroup } from "../../src/commands/triggers.js";
import { CLIError } from "../../src/framework/errors.js";

describe("triggers commands", () => {
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

  it("register requires --repo, --workflow, --event", async () => {
    const handler = triggersGroup.getCommand("register")!.handler;
    await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    await expect(handler({ positionals: [], values: { repo: "r1" } })).rejects.toThrow(CLIError);
    await expect(handler({ positionals: [], values: { repo: "r1", workflow: "w1" } })).rejects.toThrow(CLIError);
  });

  it("register succeeds with required options", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ trigger_id: "trig-1" }));
    const handler = triggersGroup.getCommand("register")!.handler;
    await handler({
      positionals: [],
      values: { repo: "r1", workflow: "w1", event: "check_run.completed" },
    });
    expect(stdout()).toContain("Trigger registered");
  });

  it("list shows triggers table", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({ triggers: [
        { trigger_id: "trig-1", event: "push", repository: "r1", workflow_id: "w1", status: "active", fire_count: 3 },
      ], total: 1 }),
    );
    await triggersGroup.getCommand("list")!.handler({ positionals: [], values: {} });
    expect(stdout()).toContain("trig-1");
  });

  it("show displays trigger details", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        trigger_id: "trig-1",
        event: "push",
        repository: "r1",
        workflow_id: "w1",
        status: "active",
        fire_count: 5,
        max_fires_per_period: 10,
        cooldown_seconds: 300,
        conditions: [{ field: "branch", operator: "eq", value: "main" }],
      }),
    );
    await triggersGroup.getCommand("show")!.handler({ positionals: ["trig-1"], values: {} });
    const out = stdout();
    expect(out).toContain("trig-1");
    expect(out).toContain("branch");
    expect(out).toContain("main");
  });

  it("delete requires --force", async () => {
    await expect(
      triggersGroup.getCommand("delete")!.handler({ positionals: ["trig-1"], values: {} }),
    ).rejects.toThrow(CLIError);
  });

  it("pause sends request", async () => {
    const detail = {
      trigger_id: "trig-1",
      name: "test",
      event: "push",
      repository: "r1",
      workflow_id: "w1",
      status: "paused",
      fire_count: 0,
      installation_id: "inst-1",
      created_by: "cli",
    };
    // PATCH (action) then GET (re-fetch detail)
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ trigger_id: "trig-1", status: "paused" }))
      .mockResolvedValueOnce(jsonResponse(detail));
    await triggersGroup.getCommand("pause")!.handler({ positionals: ["trig-1"], values: {} });
    expect(stdout()).toContain("paused");
  });
});
