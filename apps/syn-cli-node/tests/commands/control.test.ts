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
    vi.resetAllMocks();
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

  it("inject prints the API's refusal and exits non-zero (#1530)", async () => {
    const refusal =
      "Injecting a message into a running agent is not supported; cancel the execution and start again with a corrected task (#1530).";
    mockFetch.mockResolvedValue(jsonResponse({ detail: refusal }, 501));
    const handler = controlGroup.getCommand("inject")!.handler;

    const error = await handler({ positionals: ["exec-1"], values: { message: "m" } }).then(
      () => undefined,
      (e: unknown) => e,
    );

    expect(error).toBeInstanceOf(CLIError);
    expect((error as CLIError).exitCode).not.toBe(0);
    expect((error as CLIError).message).toContain(refusal);
    expect(stdout()).not.toContain("injected");
  });

  it("inject refuses non-zero when an old server answers 200 queued (#1530)", async () => {
    // The response every server before #1530 gave: it queued, and nothing delivers.
    mockFetch.mockResolvedValue(
      jsonResponse({
        success: true,
        execution_id: "exec-1",
        state: "running",
        message: "Context injection queued",
      }),
    );
    const handler = controlGroup.getCommand("inject")!.handler;

    const error = await handler({ positionals: ["exec-1"], values: { message: "m" } }).then(
      () => undefined,
      (e: unknown) => e,
    );

    expect(error).toBeInstanceOf(CLIError);
    expect((error as CLIError).exitCode).not.toBe(0);
    expect((error as CLIError).message).toContain("not supported");
    expect((error as CLIError).message).toContain("start again with a corrected task");
    expect(stdout()).toBe("");
  });

  it("stop requires --force", async () => {
    const handler = controlGroup.getCommand("stop")!.handler;
    await expect(handler({ positionals: ["exec-1"], values: {} })).rejects.toThrow(CLIError);
  });
});
