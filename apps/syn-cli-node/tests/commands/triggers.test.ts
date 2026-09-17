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
    vi.unstubAllEnvs();
  });

  // Two distinct non-default hosts. DISPATCHED_TO is what the client is built
  // from; LATER is where the environment moves afterwards. A report naming
  // LATER read the environment rather than the client it actually sent
  // through — the #1264 failure in miniature.
  const DISPATCHED_TO = "http://100.112.178.5:8137";
  const LATER = "http://100.114.86.77:8137";

  /** Re-import the trigger commands with the client bound to DISPATCHED_TO. */
  async function triggersBoundToVps(): Promise<typeof triggersGroup> {
    vi.stubEnv("SYN_API_URL", DISPATCHED_TO);
    vi.resetModules();
    const { triggersGroup: fresh } = await import("../../src/commands/triggers.js");
    vi.stubEnv("SYN_API_URL", LATER);
    return fresh;
  }

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

  it("register names the deployment the trigger will fire workflows on (issue #1264)", async () => {
    // A trigger holds a host-relative workflow ID and fires it LATER, so the
    // ambiguity outlives the command: the report has to pin the workflow ID to
    // the host it was registered against.
    const group = await triggersBoundToVps();
    mockFetch.mockResolvedValue(jsonResponse({ trigger_id: "trig-vps-1", status: "active" }));

    await group.getCommand("register")!.handler({
      positionals: [],
      values: { repo: "org/repo", workflow: "wf-selfheal-42", event: "check_run.completed" },
    });

    const registerReq = mockFetch.mock.calls[0]![0] as Request;
    const registeredOn = new URL(registerReq.url).origin;
    expect(registeredOn).toBe(DISPATCHED_TO);
    const posted = JSON.parse(await registerReq.clone().text()) as { workflow_id: string };
    expect(posted.workflow_id).toBe("wf-selfheal-42");

    const out = stdout();
    expect(out).toContain(registeredOn);
    expect(out).toContain(posted.workflow_id);
    expect(out).toContain("trig-vps-1");
    expect(out).not.toContain(LATER);
  });

  it("enable names the deployment the preset will dispatch on (issue #1264)", async () => {
    const group = await triggersBoundToVps();
    mockFetch.mockResolvedValue(jsonResponse({ trigger_id: "trig-preset-1", status: "active" }));

    await group.getCommand("enable")!.handler({
      positionals: ["self-healing"],
      values: { repo: "org/repo", workflow: "wf-preset-77" },
    });

    const enableReq = mockFetch.mock.calls[0]![0] as Request;
    const enabledOn = new URL(enableReq.url).origin;
    expect(enabledOn).toBe(DISPATCHED_TO);
    const posted = JSON.parse(await enableReq.clone().text()) as { workflow_id: string };
    expect(posted.workflow_id).toBe("wf-preset-77");

    const out = stdout();
    expect(out).toContain(enabledOn);
    expect(out).toContain(posted.workflow_id);
    expect(out).toContain("trig-preset-1");
    expect(out).not.toContain(LATER);
  });

  it("resume names the deployment the re-armed trigger will fire on (issue #1264)", async () => {
    // Not one of the five the review enumerated, but the same class: resuming
    // re-arms a standing instruction to start workflows on a specific host.
    const group = await triggersBoundToVps();
    mockFetch.mockResolvedValue(jsonResponse({ trigger_id: "trig-armed-1", status: "active" }));

    await group.getCommand("resume")!.handler({ positionals: ["trig-armed-1"], values: {} });

    const resumeReq = mockFetch.mock.calls[0]![0] as Request;
    const armedOn = new URL(resumeReq.url).origin;
    expect(armedOn).toBe(DISPATCHED_TO);

    const out = stdout();
    expect(out).toContain(armedOn);
    expect(out).toContain("trig-armed-1");
    expect(out).not.toContain(LATER);
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
        workflow_name: "PR Review",
        status: "active",
        fire_count: 5,
        config: { max_attempts: 10, cooldown_seconds: 300 },
        conditions: [{ field: "branch", operator: "eq", value: "main" }],
      }),
    );
    await triggersGroup.getCommand("show")!.handler({ positionals: ["trig-1"], values: {} });
    const out = stdout();
    expect(out).toContain("trig-1");
    // workflow_name is shown instead of workflow_id UUID
    expect(out).toContain("PR Review");
    expect(out).not.toContain("w1");
    // config safety limits are rendered
    expect(out).toContain("max 10");
    expect(out).toContain("300s");
    // conditions
    expect(out).toContain("branch");
    expect(out).toContain("main");
  });

  it("show falls back to workflow_id when workflow_name is absent", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        trigger_id: "trig-2",
        event: "push",
        repository: "r1",
        workflow_id: "w-uuid-1234",
        status: "active",
        fire_count: 0,
        conditions: [],
      }),
    );
    await triggersGroup.getCommand("show")!.handler({ positionals: ["trig-2"], values: {} });
    expect(stdout()).toContain("w-uuid-1234");
  });

  it("delete requires --force", async () => {
    await expect(
      triggersGroup.getCommand("delete")!.handler({ positionals: ["trig-1"], values: {} }),
    ).rejects.toThrow(CLIError);
  });

  it("pause sends PATCH only, no stale GET re-fetch", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ trigger_id: "trig-1", status: "paused" }));
    await triggersGroup.getCommand("pause")!.handler({ positionals: ["trig-1"], values: {} });
    expect(stdout()).toContain("paused");
    // Only one fetch call (PATCH) — no follow-up GET that would read stale projection
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("resume sends PATCH only, no stale GET re-fetch", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ trigger_id: "trig-1", status: "resumed" }));
    await triggersGroup.getCommand("resume")!.handler({ positionals: ["trig-1"], values: {} });
    expect(stdout()).toContain("resumed");
    // Only one fetch call (PATCH) — no follow-up GET that would read stale projection
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
