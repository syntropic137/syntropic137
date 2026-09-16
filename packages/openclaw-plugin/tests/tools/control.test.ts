import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SyntropicClient } from "../../src/client.js";
import {
  synCancelExecution,
  synInjectContext,
  synPauseExecution,
  synResumeExecution,
} from "../../src/tools/control.js";
import {
  controlCancel,
  controlInject,
  controlPause,
  controlResume,
} from "../fixtures/responses.js";

const mockFetch = vi.fn<typeof globalThis.fetch>();
let client: SyntropicClient;

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  client = new SyntropicClient({ apiUrl: "http://localhost:8137" });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

function jsonResponse(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("synPauseExecution", () => {
  it("pauses successfully", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(controlPause));

    const result = await synPauseExecution(client, {
      execution_id: "exec-abc-123",
      reason: "Need to review",
    });

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("paused successfully");
    expect(result.content).toContain("paused");
  });

  it("sends reason in body", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(controlPause));

    await synPauseExecution(client, { execution_id: "e1", reason: "test" });

    const [, init] = mockFetch.mock.calls[0]!;
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.reason).toBe("test");
  });
});

describe("synResumeExecution", () => {
  it("names the deployment the execution was restarted on (issue #1264)", async () => {
    // Resuming restarts work, so the result has to say WHERE: `exec-abc-123`
    // names a different run on a different deployment. Two distinct non-default
    // hosts — the client's, and one the environment offers afterwards. Naming
    // the environment's would mean the result was built from something other
    // than the client the request actually went through.
    vi.stubEnv("SYNTROPIC_URL", "http://100.114.86.77:8137");
    const vps = new SyntropicClient({ apiUrl: "http://100.112.178.5:8137" });
    mockFetch.mockResolvedValueOnce(jsonResponse(controlResume));

    const result = await synResumeExecution(vps, { execution_id: "exec-abc-123" });

    const [url] = mockFetch.mock.calls[0]!;
    const resumedOn = new URL(url as string).origin;
    expect(resumedOn).toBe("http://100.112.178.5:8137");
    expect(result.content).toContain(resumedOn);
    expect(result.content).toContain("exec-abc-123");
    expect(result.content).not.toContain("100.114.86.77");
  });

  it("resumes successfully", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(controlResume));

    const result = await synResumeExecution(client, { execution_id: "exec-abc-123" });

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("Execution Resumed");
    expect(result.content).toContain("exec-abc-123");
    expect(result.content).toContain("running");
  });
});

describe("synCancelExecution", () => {
  it("cancels successfully", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(controlCancel));

    const result = await synCancelExecution(client, { execution_id: "exec-abc-123" });

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("cancelled");
  });
});

describe("synInjectContext", () => {
  it("injects context successfully", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(controlInject));

    const result = await synInjectContext(client, {
      execution_id: "exec-abc-123",
      message: "Focus on the tests",
      role: "user",
    });

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("Context injected");
  });

  it("sends message and role in body", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(controlInject));

    await synInjectContext(client, {
      execution_id: "e1",
      message: "hello",
      role: "system",
    });

    const [, init] = mockFetch.mock.calls[0]!;
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.message).toBe("hello");
    expect(body.role).toBe("system");
  });

  it("handles failure response", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        success: false,
        execution_id: "e1",
        state: "failed",
        message: null,
        error: "No active agent",
      }),
    );

    const result = await synInjectContext(client, {
      execution_id: "e1",
      message: "test",
    });
    expect(result.isError).toBe(true);
    expect(result.content).toContain("No active agent");
  });
});
