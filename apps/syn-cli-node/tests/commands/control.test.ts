import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { controlGroup } from "../../src/commands/control.js";
import { CLIError } from "../../src/framework/errors.js";

describe("control commands", () => {
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

  it("pause sends signal", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ state: "pausing", message: "ok" }));
    const handler = controlGroup.getCommand("pause")!.handler;
    await handler({ positionals: ["exec-1"], values: {} });
    expect(stdout()).toContain("Pause signal sent");
  });

  it("resume sends signal", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ state: "running" }));
    const handler = controlGroup.getCommand("resume")!.handler;
    await handler({ positionals: ["exec-1"], values: {} });
    expect(stdout()).toContain("Resume signal sent");
  });

  it("resume names the deployment it restarted the execution on (issue #1264)", async () => {
    // Resuming restarts work, so the report has to say WHERE — `exec-1` names a
    // different run on a different host. Two distinct non-default hosts here:
    // DISPATCHED_TO is what the client is built from, LATER is where the
    // environment moved afterwards. Naming LATER would mean the command read
    // the environment instead of the client it actually sent through.
    const DISPATCHED_TO = "http://100.112.178.5:8137";
    const LATER = "http://100.114.86.77:8137";

    vi.stubEnv("SYN_API_URL", DISPATCHED_TO);
    vi.resetModules();
    const { controlGroup: freshGroup } = await import("../../src/commands/control.js");
    vi.stubEnv("SYN_API_URL", LATER);

    mockFetch.mockResolvedValue(jsonResponse({ state: "running" }));
    await freshGroup.getCommand("resume")!.handler({
      positionals: ["exec-resumed-1"],
      values: {},
    });

    const resumeReq = mockFetch.mock.calls[0]![0] as Request;
    const dispatchedTo = new URL(resumeReq.url).origin;
    expect(dispatchedTo).toBe(DISPATCHED_TO);

    const out = stdout();
    expect(out).toContain(dispatchedTo);
    expect(out).toContain("exec-resumed-1");
    expect(out).not.toContain(LATER);
  });

  it("cancel requires --force", async () => {
    const handler = controlGroup.getCommand("cancel")!.handler;
    await expect(handler({ positionals: ["exec-1"], values: {} })).rejects.toThrow(CLIError);
  });

  it("cancel with --force sends signal", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ state: "cancelled" }));
    const handler = controlGroup.getCommand("cancel")!.handler;
    await handler({ positionals: ["exec-1"], values: { force: true } });
    expect(stdout()).toContain("Cancel signal sent");
  });

  it("status shows execution state", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ state: "running" }));
    const handler = controlGroup.getCommand("status")!.handler;
    await handler({ positionals: ["exec-1"], values: {} });
    expect(stdout()).toContain("running");
  });

  it("inject requires --message", async () => {
    const handler = controlGroup.getCommand("inject")!.handler;
    await expect(handler({ positionals: ["exec-1"], values: {} })).rejects.toThrow(CLIError);
  });

  it("stop requires --force", async () => {
    const handler = controlGroup.getCommand("stop")!.handler;
    await expect(handler({ positionals: ["exec-1"], values: {} })).rejects.toThrow(CLIError);
  });
});
