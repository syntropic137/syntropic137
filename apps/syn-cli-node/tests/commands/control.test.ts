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
    mockFetch.mockResolvedValue(jsonResponse({ state: "cancelled" }));
    const handler = controlGroup.getCommand("cancel")!.handler;
    await handler({ positionals: ["exec-1"], values: { force: true } });
    expect(stdout()).toContain("Cancel signal sent");
  });

  it("cancel with a pending state caveats it as unconfirmed (#1062)", async () => {
    // Cancellation is async: the API returns the pre-enqueue state and
    // flags it as unconfirmed via state_pending. The CLI must not present
    // that value as a confirmed transition.
    mockFetch.mockResolvedValue(jsonResponse({ state: "running", state_pending: true }));
    const handler = controlGroup.getCommand("cancel")!.handler;
    await handler({ positionals: ["exec-1"], values: { force: true } });
    const out = stdout();
    expect(out).toContain("State: running (unconfirmed - transition pending)");
    expect(out).toContain("syn control status exec-1");
  });

  it("cancel with a confirmed state prints it without caveat", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ state: "completed", state_pending: false }));
    const handler = controlGroup.getCommand("cancel")!.handler;
    await handler({ positionals: ["exec-1"], values: { force: true } });
    const out = stdout();
    expect(out).toContain("State: completed");
    expect(out).not.toContain("unconfirmed");
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
