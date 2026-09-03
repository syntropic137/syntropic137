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
  });

  function jsonResponse(data: unknown, status = 200): Response {
    return new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  /**
   * What the API actually answers when a running execution is cancelled:
   * the pre-signal state, plus the message that says the signal was queued.
   * See ExecutionController._handle_cancel.
   */
  function cancelOfALiveExecution(): Response {
    return jsonResponse({ state: "running", message: "Cancel signal queued" });
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

  it("cancel requires --force", async () => {
    const handler = controlGroup.getCommand("cancel")!.handler;
    await expect(handler({ positionals: ["exec-1"], values: {} })).rejects.toThrow(CLIError);
  });

  it("cancel with --force sends signal", async () => {
    mockFetch.mockResolvedValue(cancelOfALiveExecution());
    const handler = controlGroup.getCommand("cancel")!.handler;
    await handler({ positionals: ["exec-1"], values: { force: true } });
    expect(stdout()).toContain("Cancel signal sent");
  });

  // #1062 — cancel is asynchronous. `state` is the reading taken before the
  // signal was queued, so a successful cancel of a live execution answers
  // `running`. Printed as a bare `State: running` under "Cancel signal sent"
  // that reads as a refused cancel, which is how the issue was filed.
  it("cancel labels the state as the reading from before the signal", async () => {
    mockFetch.mockResolvedValue(cancelOfALiveExecution());
    const handler = controlGroup.getCommand("cancel")!.handler;
    await handler({ positionals: ["exec-1"], values: { force: true } });
    const out = stdout();
    expect(out).toContain("State before signal: running");
    expect(out).not.toContain("State: running");
  });

  it("cancel surfaces the server's message, which says what was queued", async () => {
    // The API's honest field. The printer used to drop it for cancel and
    // resume, leaving the misleading state as the only detail on screen.
    mockFetch.mockResolvedValue(cancelOfALiveExecution());
    const handler = controlGroup.getCommand("cancel")!.handler;
    await handler({ positionals: ["exec-1"], values: { force: true } });
    expect(stdout()).toContain("Cancel signal queued");
  });

  it("resume surfaces the server's message too", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({ state: "paused", message: "Resume signal queued" }),
    );
    const handler = controlGroup.getCommand("resume")!.handler;
    await handler({ positionals: ["exec-1"], values: {} });
    const out = stdout();
    expect(out).toContain("State before signal: paused");
    expect(out).toContain("Resume signal queued");
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
