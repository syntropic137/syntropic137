import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { healthCommand } from "../../src/commands/health.js";
import { CLIError } from "../../src/framework/errors.js";

describe("health command", () => {
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

  const emptyArgs = { positionals: [] as string[], values: {} };

  it("prints healthy status", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({ status: "healthy", mode: "full" }),
    );

    await healthCommand.handler(emptyArgs);

    const output = (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls
      .map((c: unknown[]) => String(c[0]))
      .join("");
    expect(output).toContain("Healthy");
    expect(output).toContain("all systems operational");
  });

  it("prints degraded status with reasons", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        status: "healthy",
        mode: "degraded",
        degraded_reasons: "Event store disconnected",
      }),
    );

    await healthCommand.handler(emptyArgs);

    const output = (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls
      .map((c: unknown[]) => String(c[0]))
      .join("");
    expect(output).toContain("Degraded");
    expect(output).toContain("Event store disconnected");
  });

  it("throws CLIError on unhealthy status", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({ status: "unhealthy", mode: "full" }),
    );

    await expect(healthCommand.handler(emptyArgs)).rejects.toThrow(CLIError);
  });

  it("prints subscription info when present", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        status: "healthy",
        mode: "full",
        subscription: { status: "healthy", running: true },
      }),
    );

    await healthCommand.handler(emptyArgs);

    const output = (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls
      .map((c: unknown[]) => String(c[0]))
      .join("");
    expect(output).toContain("Event store: connected");
    expect(output).toContain("Subscription: healthy");
  });

  it("throws on connection failure", async () => {
    mockFetch.mockRejectedValue(new TypeError("fetch failed"));
    await expect(healthCommand.handler(emptyArgs)).rejects.toThrow();
  });
});
