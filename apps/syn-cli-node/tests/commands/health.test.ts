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

  // `degraded_reasons` is a JSON ARRAY of DegradedReason values. The previous
  // version of this test sent a string, a shape the API cannot produce, and so
  // certified a branch that never ran against a real response: every reason the
  // API sent was dropped and `syn health` said "Degraded" without saying why.
  it("prints degraded status with reasons", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        status: "healthy",
        mode: "degraded",
        degraded_reasons: ["subscription_coordinator", "projection_catchup"],
      }),
    );

    await healthCommand.handler(emptyArgs);

    const output = (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls
      .map((c: unknown[]) => String(c[0]))
      .join("");
    expect(output).toContain("Degraded");
    expect(output).toContain("subscription_coordinator");
    expect(output).toContain("projection_catchup");
  });

  // #1172: the operator's question during a replay is "which projection is
  // holding this up", and `syn health` is where they ask it.
  it("names the lagging projection while the read models rebuild", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        status: "healthy",
        mode: "degraded",
        degraded_reasons: ["projection_catchup"],
        subscription: {
          status: "catching_up",
          running: true,
          is_catching_up: true,
          lag: 4584,
          lag_unit: "events",
          head_position: 8726,
          lagging_projections: [
            { projection: "session_summaries", position: 4142, lag: 4584 },
            { projection: "workflow_executions", position: 8722, lag: 4 },
          ],
        },
      }),
    );

    await healthCommand.handler(emptyArgs);

    const output = (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls
      .map((c: unknown[]) => String(c[0]))
      .join("");
    expect(output).toContain("Subscription: catching_up");
    expect(output).toContain("session_summaries");
    expect(output).toContain("4584 events behind");
    expect(output).toContain("404");
  });

  it("says nothing about rebuilding when the read models are current", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        status: "healthy",
        mode: "full",
        subscription: {
          status: "healthy",
          running: true,
          is_catching_up: false,
          lag: 0,
          lag_unit: "events",
          head_position: 8726,
          lagging_projections: [],
        },
      }),
    );

    await healthCommand.handler(emptyArgs);

    const output = (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls
      .map((c: unknown[]) => String(c[0]))
      .join("");
    expect(output).toContain("Subscription: healthy");
    expect(output).not.toContain("Rebuilding read models");
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
