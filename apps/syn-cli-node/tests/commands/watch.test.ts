import { describe, expect, it } from "vitest";
import { watchGroup } from "../../src/commands/watch.js";

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
