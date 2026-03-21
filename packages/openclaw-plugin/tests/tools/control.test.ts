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
  it("resumes successfully", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(controlResume));

    const result = await synResumeExecution(client, { execution_id: "exec-abc-123" });

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("resumed successfully");
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
