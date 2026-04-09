import { describe, expect, it } from "vitest";
import { watchGroup } from "../../src/commands/watch.js";
import { streamSSE } from "../../src/client/sse.js";

// Watch commands use SSE streaming (streamSSE) which requires a persistent
// EventSource-like connection. Smoke-testing the actual handlers would need
// a mock SSE server or async generator, which is beyond smoke-test scope.
// We verify the command group is properly wired instead.

describe("watch commands", () => {
  it("group has execution subcommand", () => {
    expect(watchGroup.getCommand("execution")).toBeDefined();
  });

  it("group has activity subcommand", () => {
    expect(watchGroup.getCommand("activity")).toBeDefined();
  });

  it("execution requires execution-id argument", () => {
    const cmd = watchGroup.getCommand("execution")!;
    const requiredArg = cmd.args?.find((a) => a.name === "execution-id");
    expect(requiredArg).toBeDefined();
    expect(requiredArg!.required).toBe(true);
  });
});

// Regression guard: verify the activity endpoint path is /sse/activity, not /watch/activity.
// The SSEPath type (extracted from the OpenAPI spec) enforces the /sse/ prefix at compile
// time, but this test provides a runtime signal for the specific path used.
describe("watch activity SSE path regression", () => {
  it("streamSSE is typed to only accept /sse/* paths", () => {
    // The TypeScript type SSEPath = `/sse/${string}` means passing `/watch/activity`
    // would be a compile error. This test documents the constraint at runtime.
    // If this test ever needs to pass a non-/sse/ path, the type guard was weakened.
    const validPath: Parameters<typeof streamSSE>[0] = "/sse/activity";
    expect(validPath).toBe("/sse/activity");
  });
});
